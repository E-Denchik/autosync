"""Проверка и установка обновлений из GitHub Releases этого же репозитория
(тег `latest`, обновляется на каждый push в main — см.
.github/workflows/build-native.yml).

Версия "вшита" в сборку как commit SHA (scripts/write_build_info.py,
app/_build_info.json) — сравниваем его с тем commit, на который сейчас
указывает тег latest. Список изменений — авто-changelog: сообщения
коммитов между текущим и последним (GitHub compare API), без ручного
ведения release notes.

Установка платформо-зависима и всегда завершает текущий процесс (см.
_schedule_exit): Windows-инсталлятор и `apt install` на Linux не могут
перезаписать уже запущенный бинарник, поэтому реальная установка идёт в
отдельном, отсоединённом от нас процессе, который стартует ПОСЛЕ нашего
выхода, а затем сам перезапускает приложение.
"""

from __future__ import annotations

import json
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

GITHUB_REPO = "E-Denchik/autosync"
# Переопределяется в тестах/локальной проверке на мок-сервер (тот же приём,
# что и scripts/mock_ozon_api.py + OZON_SELLER_API_BASE).
GITHUB_API = os.environ.get("AUTOSYNC_GITHUB_API_BASE", "https://api.github.com")


class UpdateCheckError(RuntimeError):
    pass


class UpdateInstallError(RuntimeError):
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


def _download(url: str, dest: str) -> None:
    try:
        resp = requests.get(url, headers={"Accept": "application/octet-stream"}, stream=True, timeout=120)
    except requests.exceptions.RequestException as exc:
        raise UpdateInstallError(f"Не удалось скачать обновление: {exc}") from exc
    if not resp.ok:
        raise UpdateInstallError(f"Не удалось скачать обновление: GitHub -> {resp.status_code}")
    total = 0
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1024 * 256):
            f.write(chunk)
            total += len(chunk)
    if total == 0:
        raise UpdateInstallError("Скачанный файл обновления пуст")


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


def _install_windows(assets: list[dict]) -> None:
    asset = next(
        (a for a in assets if a["name"].startswith("autosync-setup") and a["name"].endswith(".exe")), None
    )
    if not asset:
        raise UpdateInstallError("В последнем релизе не найден установщик Windows.")

    tmp_dir = tempfile.mkdtemp(prefix="autosync-update-")
    installer_path = os.path.join(tmp_dir, asset["name"])
    _download(asset["browser_download_url"], installer_path)

    current_exe = _running_binary_path()
    # 2 секунды — чтобы наш процесс успел выйти и освободить файл: Windows
    # не даёт инсталлятору перезаписать exe, пока он ещё запущен.
    script_path = os.path.join(tmp_dir, "apply_update.bat")
    with open(script_path, "w", encoding="mbcs", errors="ignore") as f:
        f.write(
            "@echo off\r\n"
            "timeout /t 2 /nobreak >nul\r\n"
            f'"{installer_path}" /SILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS\r\n'
            f'start "" "{current_exe}"\r\n'
        )

    subprocess.Popen(
        ["cmd", "/c", script_path],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
        env=_relaunch_env(),
    )
    _schedule_exit()


def _install_linux(assets: list[dict]) -> None:
    current_exe = _running_binary_path()
    tmp_dir = tempfile.mkdtemp(prefix="autosync-update-")
    is_deb_install = current_exe.startswith("/opt/autosync/")

    if is_deb_install:
        asset = next(
            (a for a in assets if a["name"].startswith("autosync-desktop") and a["name"].endswith(".deb")), None
        )
        if not asset:
            raise UpdateInstallError("В последнем релизе не найден .deb-пакет.")
        deb_path = os.path.join(tmp_dir, asset["name"])
        _download(asset["browser_download_url"], deb_path)

        # apt install запросит пароль через графический диалог (pkexec).
        # Если пользователь отменит или установка не удастся — всё равно
        # перезапускаем то, что лежит по текущему пути: dpkg атомарен,
        # старая рабочая версия остаётся на месте, приложение не потеряется.
        script = (
            "#!/bin/sh\n"
            "sleep 2\n"
            f"pkexec apt-get install -y --allow-downgrades '{deb_path}' || true\n"
            f"'{current_exe}' &\n"
        )
    else:
        asset = next((a for a in assets if a.get("name") == "autosync"), None)
        if not asset:
            raise UpdateInstallError("В последнем релизе не найден бинарник Linux.")
        new_binary_path = os.path.join(tmp_dir, "autosync-new")
        _download(asset["browser_download_url"], new_binary_path)
        os.chmod(new_binary_path, os.stat(new_binary_path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        # cp, не mv — tmp_dir может быть на другой файловой системе
        # (например, tmpfs), mv между ФС падает с "Invalid cross-device link".
        script = (
            "#!/bin/sh\n"
            "sleep 2\n"
            f"cp -f '{new_binary_path}' '{current_exe}'\n"
            f"chmod +x '{current_exe}'\n"
            f"'{current_exe}' &\n"
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


def install_update() -> None:
    if not is_frozen():
        raise UpdateInstallError("Установка обновления доступна только в собранном приложении.")

    release = _get(f"{GITHUB_API}/repos/{GITHUB_REPO}/releases/tags/latest")
    assets = release.get("assets", [])

    system = platform.system()
    if system == "Windows":
        _install_windows(assets)
    elif system == "Linux":
        _install_linux(assets)
    else:
        raise UpdateInstallError(f"Автообновление не поддерживается на {system}.")
