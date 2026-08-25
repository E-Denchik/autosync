"""Проверка и установка обновлений из GitHub Releases этого же репозитория
(тег `latest`, обновляется на каждый push в main — см.
.github/workflows/build-native.yml).

Версия "вшита" в сборку как commit SHA (scripts/write_build_info.py,
app/_build_info.json) — сравниваем его с тем commit, на который сейчас
указывает тег latest. Список изменений — авто-changelog: сообщения
коммитов между текущим и последним (GitHub compare API), без ручного
ведения release notes.

Скачивание и применение обновления — два РАЗДЕЛЬНЫХ шага, а не один
блокирующий вызов (см. историю багов: раньше install_update() скачивал и
сразу же ставил внутри одного HTTP-запроса — фронт физически не мог
показать прогресс скачивания, потому что к моменту получения ответа файл
уже был скачан целиком). Скачивание идёт в фоновом потоке и пишет прогресс
в общее состояние (get_download_state()), которое фронт опрашивает поллингом.
Установка ждёт явного подтверждения пользователя (apply_update()).

Установка платформо-зависима и всегда завершает текущий процесс (см.
_schedule_exit): Windows-инсталлятор и `apt install`/`cp` на Linux не могут
перезаписать уже запущенный бинарник, поэтому реальная установка идёт в
отдельном, отсоединённом от нас процессе, который стартует ПОСЛЕ нашего
выхода, а затем сам перезапускает приложение.

Раньше обе ветки установки ГЛОТАЛИ ошибку молча (Windows:
/SUPPRESSMSGBOXES прятал любую ошибку инсталлятора; Linux: `|| true` после
pkexec/apt-get) и всё равно перезапускали СТАРЫЙ бинарник — снаружи это
выглядело как "нажал установить, а обновление всё равно предлагается
заново" при каждой следующей проверке, без единой подсказки почему. Теперь
перед запуском установщика пишется маркер с ожидаемым исходом
(_write_pending_marker), а установочный скрипт дополнительно сохраняет код
возврата самого инсталлятора/apt-get/cp. При следующем запуске
consume_pending_update_result() сравнивает вшитый в НОВЫЙ процесс commit с
тем, что было "до" — если они совпали, установка не применилась, и
причина (код возврата) показывается пользователю вместо тишины."""

from __future__ import annotations

import json
import logging
import os
import platform
import stat
import subprocess
import sys
import tempfile
import threading
import time

import requests

from app.config import _bundled_resource

logger = logging.getLogger(__name__)

GITHUB_REPO = "E-Denchik/autosync"
# Переопределяется в тестах/локальной проверке на мок-сервер (тот же приём,
# что и scripts/mock_ozon_api.py + OZON_SELLER_API_BASE).
GITHUB_API = os.environ.get("AUTOSYNC_GITHUB_API_BASE", "https://api.github.com")


class UpdateCheckError(RuntimeError):
    pass


class UpdateInstallError(RuntimeError):
    pass


class _DownloadCanceled(Exception):
    pass


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def get_current_commit() -> str | None:
    if not is_frozen():
        return None
    path = _bundled_resource("app", "_build_info.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f).get("commit")
    except Exception:
        return None


def _get(url: str) -> dict:
    try:
        resp = requests.get(url, headers={"Accept": "application/vnd.github+json"}, timeout=15)
    except requests.exceptions.RequestException as exc:
        raise UpdateCheckError(f"GitHub недоступен: {exc}") from exc
    if resp.status_code == 404:
        raise UpdateCheckError(
            "Релиз latest не найден на GitHub (404) — либо репозиторий ещё приватный, "
            "либо сборка ещё ни разу не публиковалась."
        )
    if not resp.ok:
        raise UpdateCheckError(f"GitHub API -> {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def check_for_update() -> dict:
    current_commit = get_current_commit()
    if not current_commit or current_commit == "unknown":
        raise UpdateCheckError(
            "Эта сборка не содержит информацию о своей версии — проверка обновлений недоступна."
        )

    ref = _get(f"{GITHUB_API}/repos/{GITHUB_REPO}/git/refs/tags/latest")
    latest_commit = ref["object"]["sha"]

    if latest_commit == current_commit:
        return {
            "update_available": False,
            "current_commit": current_commit,
            "latest_commit": latest_commit,
            "changes": [],
        }

    changes: list[str] = []
    try:
        compare = _get(f"{GITHUB_API}/repos/{GITHUB_REPO}/compare/{current_commit}...{latest_commit}")
        changes = [c["commit"]["message"].splitlines()[0] for c in compare.get("commits", [])]
    except UpdateCheckError:
        # Собственный commit может оказаться слишком старым для compare
        # (история переписана и т.п.) — само наличие обновления это не отменяет.
        pass

    return {
        "update_available": True,
        "current_commit": current_commit,
        "latest_commit": latest_commit,
        "changes": changes,
    }


def _running_binary_path() -> str:
    return os.path.abspath(sys.executable)


def _relaunch_env() -> dict:
    """Окружение для процесса, который запускает обновлённый бинарник.

    PyInstaller onefile прокидывает своим дочерним процессам переменные
    вроде _MEIPASS2/_PYI_APPLICATION_HOME_DIR/LD_LIBRARY_PATH, указывающие
    на СВОЮ распакованную временную папку (/tmp/_MEIxxxxxx) — так re-exec
    того же бинарника не распаковывается заново. Если их унаследует ДРУГОЙ
    файл по тому же пути (только что подменённый нами), он попытается
    переиспользовать уже удалённую (когда наш процесс вышел) папку и не
    запустится вовсе — "Failed to load Python shared library ... No such
    file or directory". Без них загрузчик просто распакует себя заново,
    как при обычном запуске — что и нужно."""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("_PYI_") or key == "_MEIPASS2" or key == "LD_LIBRARY_PATH":
            env.pop(key, None)
    return env


def _schedule_exit(delay: float = 1.5) -> None:
    def _exit() -> None:
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()


# ---------------------------------------------------------------------------
# Скачивание — фоновый поток с прогрессом
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()
_state: dict = {
    # idle -> downloading -> downloaded -> applying (после чего процесс
    # завершается сам, см. _schedule_exit) | error | canceled
    "phase": "idle",
    "downloaded_bytes": 0,
    "total_bytes": 0,
    "speed_bytes_per_sec": 0.0,
    "error": None,
    "asset_path": None,
    "asset_name": None,
}
_cancel_event = threading.Event()


def get_download_state() -> dict:
    with _state_lock:
        return dict(_state)


def _set_state(**kwargs) -> None:
    with _state_lock:
        _state.update(kwargs)


def _pick_asset(assets: list[dict]) -> dict:
    system = platform.system()
    if system == "Windows":
        asset = next(
            (a for a in assets if a["name"].startswith("autosync-setup") and a["name"].endswith(".exe")), None
        )
        if not asset:
            raise UpdateInstallError("В последнем релизе не найден установщик Windows.")
        return asset
    if system == "Linux":
        current_exe = _running_binary_path()
        if current_exe.startswith("/opt/autosync/"):
            asset = next(
                (a for a in assets if a["name"].startswith("autosync-desktop") and a["name"].endswith(".deb")), None
            )
            if not asset:
                raise UpdateInstallError("В последнем релизе не найден .deb-пакет.")
            return asset
        asset = next((a for a in assets if a.get("name") == "autosync"), None)
        if not asset:
            raise UpdateInstallError("В последнем релизе не найден бинарник Linux.")
        return asset
    raise UpdateInstallError(f"Автообновление не поддерживается на {system}.")


def _download_with_progress(url: str, dest: str) -> None:
    try:
        resp = requests.get(url, headers={"Accept": "application/octet-stream"}, stream=True, timeout=120)
    except requests.exceptions.RequestException as exc:
        raise UpdateInstallError(f"Не удалось скачать обновление: {exc}") from exc
    if not resp.ok:
        raise UpdateInstallError(f"Не удалось скачать обновление: GitHub -> {resp.status_code}")

    try:
        total = int(resp.headers.get("Content-Length") or 0)
    except ValueError:
        total = 0
    _set_state(total_bytes=total, downloaded_bytes=0, speed_bytes_per_sec=0.0)

    downloaded = 0
    window_start = time.monotonic()
    window_bytes = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            if _cancel_event.is_set():
                raise _DownloadCanceled()
            f.write(chunk)
            downloaded += len(chunk)
            window_bytes += len(chunk)
            now = time.monotonic()
            elapsed = now - window_start
            if elapsed >= 0.25:
                _set_state(downloaded_bytes=downloaded, speed_bytes_per_sec=window_bytes / elapsed)
                window_start = now
                window_bytes = 0
    _set_state(downloaded_bytes=downloaded)
    if downloaded == 0:
        raise UpdateInstallError("Скачанный файл обновления пуст")


def _download_job() -> None:
    try:
        release = _get(f"{GITHUB_API}/repos/{GITHUB_REPO}/releases/tags/latest")
        assets = release.get("assets", [])
        asset = _pick_asset(assets)

        tmp_dir = tempfile.mkdtemp(prefix="autosync-update-")
        dest = os.path.join(tmp_dir, asset["name"])
        _download_with_progress(asset["browser_download_url"], dest)
        _set_state(phase="downloaded", asset_path=dest, asset_name=asset["name"])
    except _DownloadCanceled:
        _set_state(phase="canceled")
    except (UpdateCheckError, UpdateInstallError) as exc:
        _set_state(phase="error", error=str(exc))
    except Exception as exc:  # не должно тихо теряться — см. докстринг модуля
        logger.exception("Скачивание обновления упало неожиданно")
        _set_state(phase="error", error=f"Непредвиденная ошибка: {exc}")


def start_download() -> None:
    if not is_frozen():
        raise UpdateInstallError("Установка обновления доступна только в собранном приложении.")
    with _state_lock:
        if _state["phase"] == "downloading":
            return  # уже идёт — повторный клик не должен запускать вторую параллельную загрузку
    _cancel_event.clear()
    _set_state(
        phase="downloading", downloaded_bytes=0, total_bytes=0, speed_bytes_per_sec=0.0, error=None, asset_path=None
    )
    threading.Thread(target=_download_job, daemon=True, name="update-download").start()


def cancel_download() -> None:
    with _state_lock:
        phase = _state["phase"]
        asset_path = _state.get("asset_path")
    if phase == "downloading":
        _cancel_event.set()
        return
    if phase == "downloaded" and asset_path and os.path.isfile(asset_path):
        try:
            os.remove(asset_path)
        except OSError:
            pass
    _set_state(phase="idle", asset_path=None, asset_name=None, error=None)


# ---------------------------------------------------------------------------
# Применение уже скачанного обновления
# ---------------------------------------------------------------------------


def _marker_path() -> str:
    data_dir = os.environ.get("AUTOSYNC_DATA_DIR") or tempfile.gettempdir()
    return os.path.join(data_dir, "pending_update.json")


def _write_pending_marker(result_path: str) -> None:
    marker = {"previous_commit": get_current_commit(), "result_path": result_path}
    try:
        with open(_marker_path(), "w", encoding="utf-8") as f:
            json.dump(marker, f)
    except OSError:
        logger.warning("Не удалось записать маркер ожидаемого обновления", exc_info=True)


def _explain_install_failure(exit_code: str | None, status: str | None = None) -> str:
    if status == "rolled_back":
        return (
            "Новая версия не запустилась после установки — приложение "
            "автоматически вернулось к предыдущей рабочей версии. Обновление "
            "не применилось, попробуйте ещё раз позже."
        )
    if status == "relaunch_failed":
        return (
            "Обновление установилось, но новая версия не запустилась при "
            "первом старте. Попробуйте запустить приложение вручную ещё раз; "
            "если не поможет — переустановите вручную с GitHub Releases."
        )
    if exit_code is None:
        return (
            "Не удалось подтвердить установку обновления — возможно, приложение "
            "было закрыто до её завершения."
        )
    if exit_code.strip() == "0":
        return "Установщик отработал без ошибок, но версия приложения не изменилась. Попробуйте ещё раз."
    return f"Установка обновления завершилась с ошибкой (код {exit_code.strip()})."


def consume_pending_update_result() -> dict | None:
    """Вызывается один раз при старте приложения — проверяет, применилось ли
    обновление, запущенное перед ЭТИМ запуском. См. докстринг модуля про
    то, почему раньше это тихо терялось."""
    path = _marker_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            marker = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

    previous_commit = marker.get("previous_commit")
    result_path = marker.get("result_path")
    current_commit = get_current_commit()

    exit_code = None
    status = None
    if result_path and os.path.isfile(result_path):
        try:
            # utf-8-sig, не utf-8: на Windows этот файл пишет PowerShell
            # (Set-Content -Encoding utf8), а Windows PowerShell 5.1 в режиме
            # "utf8" всегда добавляет BOM — с обычным utf-8 это превратило бы
            # exit_code "0" в "﻿0", str.strip() BOM не убирает, и
            # успешную установку было бы не отличить от неудачной. На Linux
            # (echo $? без BOM) utf-8-sig читает как обычный utf-8.
            with open(result_path, "r", encoding="utf-8-sig") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
            exit_code = lines[0] if lines else None
            # Вторая строка — необязательная отметка о том, что новый процесс
            # не пережил перезапуск (см. _apply_linux/_apply_windows): либо
            # "rolled_back" (Linux, не .deb: старый бинарник восстановлен
            # автоматически), либо "relaunch_failed" (.deb/Windows — там
            # безопасного отката нет, только диагностика).
            status = lines[1] if len(lines) > 1 else None
        except OSError:
            pass
        try:
            os.remove(result_path)
        except OSError:
            pass

    if current_commit and previous_commit and current_commit != previous_commit:
        return {"success": True, "commit": current_commit}

    return {"success": False, "exit_code": exit_code, "message": _explain_install_failure(exit_code, status)}


def _apply_windows(installer_path: str) -> None:
    asset_name = os.path.basename(installer_path)
    if not (asset_name.startswith("autosync-setup") and asset_name.endswith(".exe")):
        raise UpdateInstallError("Скачанный файл не похож на установщик Windows.")

    tmp_dir = os.path.dirname(installer_path)
    current_exe = _running_binary_path()
    result_path = os.path.join(tmp_dir, "install_result.txt")
    _write_pending_marker(result_path)

    # /SILENT (не /VERYSILENT) — Inno Setup сам показывает нативное окно
    # прогресса установки, этого достаточно, чтобы пользователь видел,
    # что происходит, без отдельного кастомного UI. /SUPPRESSMSGBOXES
    # раньше прятал вместе с прогрессом и реальные ошибки инсталлятора —
    # убран намеренно (см. докстринг модуля).
    #
    # PowerShell, а не .bat: Start-Process -PassThru отдаёт настоящий объект
    # процесса с его PID и .ExitCode — можно точно проверить, что запустился
    # (и жив) именно ТОТ процесс, который мы сами создали, а не какой-то
    # чужой процесс с тем же именем образа (то, чем грешит сопоставление
    # через tasklist/find по имени в .bat). Дополнительно уходит зависимость
    # от кодировки "mbcs": Windows PowerShell по умолчанию читает файл
    # скрипта в системной ANSI-кодовой странице, если в начале файла нет
    # BOM, — путь с кириллицей (например, C:\Users\Иван\AppData\...,
    # обычное дело для установщика в %TEMP%) в .bat без BOM/с "mbcs" рисковал
    # прочитаться неверно и сломать установку. utf-8-sig ниже пишет BOM.
    #
    # Отката к предыдущей версии на Windows не делаем (файлы под управлением
    # Inno Setup, безопасный бэкап — отдельная большая задача) — только
    # честно сообщаем о неудавшемся перезапуске при следующем старте.
    script_path = os.path.join(tmp_dir, "apply_update.ps1")
    ps_installer_path = installer_path.replace("'", "''")
    ps_current_exe = current_exe.replace("'", "''")
    ps_result_path = result_path.replace("'", "''")
    with open(script_path, "w", encoding="utf-8-sig") as f:
        f.write(
            "Start-Sleep -Seconds 2\n"
            f"$installerProc = Start-Process -FilePath '{ps_installer_path}' "
            "-ArgumentList '/SILENT','/NORESTART','/CLOSEAPPLICATIONS' -Wait -PassThru\n"
            f"Set-Content -Path '{ps_result_path}' -Value $installerProc.ExitCode -Encoding utf8 -NoNewline\n"
            f"$newProc = Start-Process -FilePath '{ps_current_exe}' -PassThru\n"
            "Start-Sleep -Seconds 3\n"
            "$stillAlive = Get-Process -Id $newProc.Id -ErrorAction SilentlyContinue\n"
            "if (-not $stillAlive) {\n"
            f"    Add-Content -Path '{ps_result_path}' -Value \"`nrelaunch_failed\"\n"
            "}\n"
        )

    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", script_path],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        env=_relaunch_env(),
    )
    _schedule_exit()


def _apply_linux(asset_path: str) -> None:
    current_exe = _running_binary_path()
    tmp_dir = os.path.dirname(asset_path)
    is_deb_install = current_exe.startswith("/opt/autosync/")
    result_path = os.path.join(tmp_dir, "install_result.txt")
    _write_pending_marker(result_path)

    if is_deb_install:
        if not asset_path.endswith(".deb"):
            raise UpdateInstallError("Скачанный файл не похож на .deb-пакет.")
        # pkexec запросит пароль через графический диалог. Раньше `|| true`
        # после этой команды тихо проглатывал любой отказ (отменённый ввод
        # пароля, конфликт пакетов и т.п.) — теперь код возврата реально
        # сохраняется и показывается пользователю при следующем запуске
        # (см. consume_pending_update_result), вместо того чтобы просто
        # молча перезапустить старую версию.
        # Как и на Windows, после apt-get install нет гарантии, что новая
        # версия реально запустится (пакет мог собраться битым — ровно так
        # уже случалось локально с pywebview/gi, см. build-native-linux.sh).
        # apt не даёт нам безопасный локальный откат без заранее сохранённого
        # старого .deb, поэтому здесь только фиксируем факт неудачи для
        # следующего запуска, без автоматического отката.
        script = (
            "#!/bin/sh\n"
            "sleep 2\n"
            f"pkexec apt-get install -y --allow-downgrades '{asset_path}'\n"
            f"echo $? > '{result_path}'\n"
            f"'{current_exe}' &\n"
            "NEWPID=$!\n"
            "sleep 3\n"
            f"kill -0 \"$NEWPID\" 2>/dev/null || echo relaunch_failed >> '{result_path}'\n"
        )
    else:
        os.chmod(asset_path, os.stat(asset_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        # cp, не mv — tmp_dir может быть на другой файловой системе
        # (например, tmpfs), mv между ФС падает с "Invalid cross-device link").
        #
        # Здесь, в отличие от .deb/Windows, у нас есть простой путь к
        # безопасному откату: старый бинарник — это один файл, который мы и
        # так вот-вот перезапишем, так что бэкапим его перед подменой. Если
        # новый процесс не пережил первые секунды (тот самый класс багов —
        # сборка "прошла", но собранный бинарник не может открыть окно),
        # автоматически возвращаем рабочую версию назад и перезапускаем её,
        # вместо того чтобы оставить пользователя с полностью нерабочим
        # приложением до ручной переустановки.
        backup_path = os.path.join(tmp_dir, "autosync.backup")
        script = (
            "#!/bin/sh\n"
            "sleep 2\n"
            f"cp -f '{current_exe}' '{backup_path}'\n"
            f"cp -f '{asset_path}' '{current_exe}' && chmod +x '{current_exe}'\n"
            f"echo $? > '{result_path}'\n"
            f"'{current_exe}' &\n"
            "NEWPID=$!\n"
            "sleep 3\n"
            "if kill -0 \"$NEWPID\" 2>/dev/null; then\n"
            f"  rm -f '{backup_path}'\n"
            "else\n"
            f"  echo rolled_back >> '{result_path}'\n"
            f"  cp -f '{backup_path}' '{current_exe}' && chmod +x '{current_exe}'\n"
            f"  rm -f '{backup_path}'\n"
            f"  '{current_exe}' &\n"
            "fi\n"
        )

    script_path = os.path.join(tmp_dir, "apply_update.sh")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    os.chmod(script_path, 0o755)

    subprocess.Popen(
        ["/bin/sh", script_path],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=_relaunch_env(),
    )
    _schedule_exit()


def apply_update() -> None:
    if not is_frozen():
        raise UpdateInstallError("Установка обновления доступна только в собранном приложении.")

    with _state_lock:
        phase = _state["phase"]
        asset_path = _state.get("asset_path")
    if phase != "downloaded" or not asset_path or not os.path.isfile(asset_path):
        raise UpdateInstallError("Сначала нужно скачать обновление.")

    _set_state(phase="applying")

    system = platform.system()
    try:
        if system == "Windows":
            _apply_windows(asset_path)
        elif system == "Linux":
            _apply_linux(asset_path)
        else:
            raise UpdateInstallError(f"Автообновление не поддерживается на {system}.")
    except Exception as exc:
        _set_state(phase="error", error=str(exc))
        raise
