"""Точка входа для 'обычного приложения' — запуск AutoSync на Windows/Linux
без Docker: backend + llm-service (тонкая обёртка над Ollama) в одном
процессе на двух локальных портах, SQLite, APScheduler и ThreadPoolExecutor
вместо внешней очереди задач (см. app/config.py, app/services/job_queue.py).

Открывается в собственном окне (pywebview — системный webview: WebView2 на
Windows, WebKitGTK на Linux, без Chromium внутри), а не в браузере — единая
точка входа, закрытие окна полностью завершает приложение (включая фоновые
задачи вроде планового синка цен по Ozon). Backend слушает только
127.0.0.1 — AutoSync недоступен ни из браузера на этой машине, ни тем более
из браузера с других устройств в сети: единственный способ работать с
приложением — это окно, которое открывает сам процесс. Логи пишутся в файл
рядом с базой данных, т.к. у frozen-бинарника обычно нет консоли.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import secrets
import sys
import threading
import time

logger = logging.getLogger("autosync.native")

if sys.platform.startswith("linux"):
    # WebKitGTK's DMA-BUF renderer сегфолтит на части систем без полноценного
    # GPU-доступа (виртуалки, некоторые песочницы/контейнеры, старые драйверы
    # Mesa) — без этого флага окно может не открыться вовсе. Программный
    # рендеринг чуть медленнее, но для админ-панели это не критично.
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

    # На части систем (замечено на Kali/lightdm) GTK-сессия почему-то
    # наследует чужой AT-SPI accessibility bus (адрес рантайма другого UID,
    # например lightdm вместо текущего пользователя) — подключение к нему
    # падает, а libatk-bridge2.0 вместо аккуратного фолбэка сегфолтит сразу
    # при старте окна (баг самой библиотеки, не нашего кода). AutoSync —
    # админ-панель без запроса на screen-reader поддержку, поэтому просто не
    # даём GTK пытаться подключаться к accessibility bus вообще.
    os.environ.setdefault("NO_AT_BRIDGE", "1")

    # GTK_MODULES/GTK3_MODULES прописаны в самой X-сессии рабочего стола
    # (на Kali/XFCE это /etc/X11/Xsession.d/*: appmenu-gtk-module — из
    # GTK_MODULES, xapp-gtk3-module — из отдельной, GTK3-специфичной
    # GTK3_MODULES) — это никак не связано с AutoSync и так же ломается для
    # ЛЮБОГО GTK3-приложения в этой сессии, если сам .so модуля не
    # зарегистрирован: GTK просто печатает "Failed to load module" в stderr
    # и продолжает работать как обычно. Выглядит как ошибка при запуске из
    # терминала, поэтому просто не наследуем эти списки для своего процесса.
    os.environ.pop("GTK_MODULES", None)
    os.environ.pop("GTK3_MODULES", None)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def resource_path(*parts: str) -> str:
    """Путь к ресурсу, упакованному вместе с приложением (см. также
    app/config.py: _bundled_resource — та же логика, здесь нужна раньше,
    ещё до импорта app.*)."""
    if is_frozen():
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, *parts)


def get_icon_path() -> str | None:
    """Иконка окна/панели задач — см. packaging/icon/. На Windows pywebview
    (winforms-бэкенд) создаёт System.Drawing.Icon() напрямую из файла и
    падает, если это не .ico — PNG там не подходит, в отличие от GTK/Cocoa
    (Linux/macOS), которые сами читают PNG. Файл упакован отдельно от
    llm_service_src/migrations, см. --add-data в build-native-*.

    Отсутствие иконки не должно ронять приложение — просто останется
    иконка по умолчанию, поэтому возвращаем None вместо исключения."""
    name = "icon.ico" if sys.platform == "win32" else "icon.png"
    if is_frozen():
        path = resource_path("icon", name)
    else:
        path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "packaging", "icon", name)
        )
    if not os.path.isfile(path):
        logger.warning("Иконка приложения не найдена: %s", path)
        return None
    return path


def configure_tesseract() -> None:
    if sys.platform != "win32" or not is_frozen():
        return
    bundle_dir = resource_path("tesseract")
    exe_path = os.path.join(bundle_dir, "tesseract.exe")
    if not os.path.isfile(exe_path):
        logger.warning("Tesseract не найден в сборке (%s) — загрузка сканов/фото будет недоступна.", exe_path)
        return
    import pytesseract

    pytesseract.pytesseract.tesseract_cmd = exe_path
    os.environ["TESSDATA_PREFIX"] = os.path.join(bundle_dir, "tessdata")


def get_data_dir() -> str:
    override = os.environ.get("AUTOSYNC_DATA_DIR")
    if override:
        return override
    if is_frozen():
        # Установленное приложение — не живёт рядом с исходниками, поэтому
        # использует каталог данных ОС (см. также app/config.py:
        # _default_data_dir(), тот же выбор).
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
            return os.path.join(base, "AutoSync")
        if sys.platform == "darwin":
            return os.path.expanduser("~/Library/Application Support/AutoSync")
        return os.path.expanduser("~/.autosync")
    # Запуск из исходников — БД и загрузки живут внутри репозитория (data/,
    # см. .gitignore), а не в домашнем каталоге пользователя.
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, "data")


def setup_logging(data_dir: str) -> None:
    # force=True — alembic.ini содержит [logger_root] (level=WARN,
    # handlers=console), которую migrations/env.py применяет через
    # logging.config.fileConfig() при каждом flask db upgrade(). Без force
    # это молча выкидывает наш FileHandler и поднимает уровень root-логгера
    # до WARN — все info-логи после первой миграции идут в никуда. Поэтому
    # main() зовёт setup_logging() второй раз сразу после upgrade(), чтобы
    # отбить её обратно.
    log_path = os.path.join(data_dir, "autosync.log")
    handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    if not is_frozen():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def load_llm_service_app():
    """Загружает llm-service/server.py как модуль — тот же файл, что и
    Docker-образ llm-service использует напрямую (единая точка обёртки
    над Ollama, см. ARCHITECTURE.md).

    Frozen-бинарник: файл упакован как data ("llm_service_src", см.
    scripts/build-native.sh). Запуск из исходников: он просто лежит
    рядом, в ../llm-service/.
    """
    if is_frozen():
        server_path = resource_path("llm_service_src", "server.py")
    else:
        server_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "llm-service", "server.py")
        )
    spec = importlib.util.spec_from_file_location("autosync_llm_server", server_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.app


def run_llm_service(port: int) -> None:
    from waitress import serve

    os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    os.environ.setdefault("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234/v1")
    app = load_llm_service_app()
    logger.info("llm-service слушает на 127.0.0.1:%s", port)
    serve(app, host="127.0.0.1", port=port, _quiet=True)


def run_backend(app, port: int) -> None:
    from waitress import serve

    # Только 127.0.0.1 — AutoSync должен работать исключительно через своё
    # окно (см. run_window), не через браузер ни с этой машины, ни тем более
    # с других устройств в сети.
    logger.info("backend слушает на 127.0.0.1:%s", port)
    serve(app, host="127.0.0.1", port=port, _quiet=True)


def start_scheduler(app):
    from apscheduler.schedulers.background import BackgroundScheduler

    # Импортируем здесь, но ДО старта планировщика (т.е. ещё в главном
    # потоке) — если импортировать внутри _sync_job, первый вызов случится
    # только через 6 часов из потока APScheduler, а первый импорт модуля не
    # из главного потока в PyInstaller-сборке проходит тихо и без эффекта
    # (см. аналогичный фикс в services/job_queue.py).
    from app.services.catalog_sync import sync_ozon_catalog_job
    from app.services.price_sync import sync_ozon_prices_job

    def _sync_job():
        with app.app_context():
            # Сначала каталог (создаёт/обновляет товары из Ozon), потом цены —
            # иначе price_sync не найдёт только что появившиеся товары до
            # следующего цикла.
            try:
                sync_ozon_catalog_job()
            except Exception:
                logger.exception("sync_ozon_catalog_job упал")
            try:
                sync_ozon_prices_job()
            except Exception:
                logger.exception("sync_ozon_prices_job упал")

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_sync_job, "interval", hours=6, id="sync_ozon_prices", next_run_time=None)
    scheduler.start()
    return scheduler


class SaveDialogApi:
    """js_api-мост для фронта: JS сам не может открыть системное окно
    "Сохранить как" — это умеет только объект окна pywebview, доступный
    только в этом процессе. Фронт вместо скрытого <a download> (см. историю
    багов — файл незаметно падал в системную папку загрузок, и не было
    способа выбрать место/имя/формат) вызывает
    window.pywebview.api.save_file_dialog(...), которая открывает настоящий
    диалог ОС и пишет файл туда, куда указал пользователь.

    Экземпляр создаётся до create_window (pywebview требует js_api на
    момент создания окна) — сам объект window подставляется в него сразу
    после того, как create_window его вернёт (см. run_window).

    Заодно — открытие ОТДЕЛЬНОГО окна прогресса обновления
    (open_update_window): пользователь просил именно системное окно
    (можно свернуть/закрыть независимо от главного), а не встроенную
    панель внутри него — JS не может создать второе нативное окно сам,
    это умеет только pywebview на этой стороне."""

    window = None
    backend_port: int | None = None
    session_token: str | None = None
    update_window = None

    def open_update_window(self) -> dict:
        import webview

        if self.update_window is not None:
            try:
                self.update_window.restore()
                self.update_window.focus()
            except Exception:
                pass
            return {"ok": True}

        if self.backend_port is None or self.session_token is None:
            return {"ok": False, "error": "Окно приложения ещё не готово"}

        url = f"http://127.0.0.1:{self.backend_port}/update-progress?token={self.session_token}"
        update_api = UpdateWindowApi(self)
        window = webview.create_window(
            "Обновление AutoSync",
            url,
            width=440,
            height=420,
            min_size=(380, 360),
            resizable=True,
            js_api=update_api,
        )
        update_api.window = window
        self.update_window = window

        def _on_closed() -> None:
            self.update_window = None

        window.events.closed += _on_closed
        return {"ok": True}

    def save_file_dialog(
        self, suggested_filename: str, content_base64: str, file_types: list[str] | None = None
    ) -> dict:
        import base64

        import webview
        from webview.util import parse_file_type

        if self.window is None:
            return {"ok": False, "error": "Окно приложения ещё не готово"}

        # create_file_dialog падает целиком, если хоть один фильтр не
        # соответствует строгому формату pywebview ("Описание (*.ext)" —
        # только буквы/цифры/пробелы в описании, никакой пунктуации, см.
        # webview.util.parse_file_type) — один опечатавшийся фильтр не
        # должен ронять сохранение файла вообще, поэтому невалидные молча
        # пропускаем, а не падаем на всём диалоге.
        valid_file_types = []
        for file_type in file_types or ():
            try:
                parse_file_type(file_type)
            except ValueError:
                logger.warning("Пропускаю некорректный фильтр файла в диалоге сохранения: %r", file_type)
                continue
            valid_file_types.append(file_type)

        try:
            result = self.window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=suggested_filename,
                file_types=tuple(valid_file_types),
            )
        except Exception as exc:
            logger.exception("create_file_dialog упал")
            return {"ok": False, "error": str(exc)}

        if not result:
            # Пользователь нажал "Отмена" — не ошибка, фронт просто не показывает тост.
            return {"ok": False, "canceled": True}

        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            data = base64.b64decode(content_base64)
            with open(path, "wb") as f:
                f.write(data)
        except Exception as exc:
            logger.exception("Не удалось записать файл через save_file_dialog: %s", path)
            return {"ok": False, "error": str(exc)}

        return {"ok": True, "path": path}


class UpdateWindowApi:
    """js_api окна прогресса обновления — единственное, что странице нужно
    от Python напрямую: закрыть СЕБЯ. window.close() в контенте pywebview
    не закрывает нативное окно (это обычная браузерная семантика, тут не
    применимо) — только сам объект Window умеет себя закрыть."""

    def __init__(self, main_api: SaveDialogApi):
        self._main_api = main_api
        self.window = None

    def close_window(self) -> dict:
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                logger.exception("Не удалось закрыть окно обновления")
        return {"ok": True}


def run_window(url: str, backend_port: int | None = None, session_token: str | None = None) -> None:
    """Открывает AutoSync в собственном окне через pywebview (системный
    webview — WebView2 на Windows, WebKitGTK на Linux, без Chromium внутри
    приложения). Закрытие окна — единственная точка выхода, полностью
    завершает процесс (см. main()): фоновые задачи (плановый синк цен)
    не переживают закрытие окна, это осознанный выбор ради простоты — одно
    окно, один процесс, без иконки в трее и скрытого фонового режима.

    Если системный webview недоступен (сломанная установка WebView2,
    отсутствующий webkit2gtk на Linux без десктопного окружения) —
    приложение завершается с понятной ошибкой в лог. Никакого отката на
    браузер по умолчанию: AutoSync — desktop-only, открыть его иначе, чем
    через это окно, не должно быть возможности в принципе (см. докстринг
    модуля)."""
    try:
        import webview
    except Exception:
        logger.error(
            "pywebview недоступен — не могу открыть окно приложения. Установите "
            "системный webview (WebView2 на Windows, python3-gi + "
            "gir1.2-webkit2-4.1 или -4.0 на Linux) и запустите AutoSync заново.",
            exc_info=True,
        )
        raise SystemExit(1)

    # Размер окна по умолчанию (1360x860) не помещался бы на небольших
    # экранах — считаем от реального разрешения текущего монитора. Плюс
    # maximized=True: окно сразу разворачивается на весь экран, на котором
    # открылось, а при переносе на другой монитор большинство оконных
    # менеджеров (X11/Wayland/Windows/macOS) сами переразворачивают
    # maximized-окно под новый экран — отдельно перехватывать смену
    # монитора pywebview не даёт (нет такого события в его API).
    try:
        screen = webview.screens[0]
        width = max(1024, min(1360, int(screen.width * 0.85)))
        height = max(700, min(860, int(screen.height * 0.85)))
    except Exception:
        width, height = 1360, 860

    save_api = SaveDialogApi()
    save_api.backend_port = backend_port
    save_api.session_token = session_token
    window = webview.create_window(
        "AutoSync", url, width=width, height=height, min_size=(1024, 700), maximized=True, js_api=save_api
    )
    save_api.window = window
    try:
        # private_mode=False — по умолчанию pywebview открывает окно как
        # приватную/инкогнито-сессию: WebKitGTK создаёт эфемерный контекст
        # и явно выключает HTML5 localStorage/persistent storage (см.
        # platforms/gtk.py). Фронт сейчас localStorage не использует, но
        # обычный (не приватный) контекст — более безопасный дефолт для
        # окна приложения в целом.
        webview.start(private_mode=False, icon=get_icon_path())
    except Exception:
        logger.error("Не удалось открыть системное окно webview.", exc_info=True)
        raise SystemExit(1)


def main() -> None:
    data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
    os.environ["AUTOSYNC_DATA_DIR"] = data_dir

    setup_logging(data_dir)
    logger.info("AutoSync запускается, каталог данных: %s", data_dir)

    configure_tesseract()

    backend_port = int(os.environ.get("AUTOSYNC_PORT", "5000"))
    llm_port = int(os.environ.get("AUTOSYNC_LLM_PORT", "8001"))
    os.environ.setdefault("LLM_SERVICE_URL", f"http://127.0.0.1:{llm_port}")

    # Токен на процесс — 127.0.0.1 доступен любому локальному клиенту
    # (включая обычный браузер, если туда просто вбить адрес), а не только
    # окну приложения. Без токена backend отвечал бы кому угодно на этой
    # машине. Ставим ДО create_app() — Config.SESSION_TOKEN читает его при
    # первом импорте app.config (см. app/config.py).
    os.environ["AUTOSYNC_SESSION_TOKEN"] = secrets.token_urlsafe(24)

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import create_app

    app = create_app()

    with app.app_context():
        from flask_migrate import upgrade

        upgrade()

        # Ключи внешних API (Ozon/аналитика), сохранённые через UI
        # (Администрирование → Интеграции, см. app/services/settings_store.py) —
        # переживают перезапуск без необходимости каждый раз задавать
        # переменные окружения вручную. setdefault: реальная переменная
        # окружения (если её всё-таки задали в терминале — например, для
        # локального мока Ozon API) остаётся приоритетнее сохранённого в БД.
        from app.services import settings_store

        settings_store.seed_baked_defaults()

        for key, value in settings_store.load_all().items():
            os.environ.setdefault(key, value)
            app.config[key] = os.environ[key]

    setup_logging(data_dir)  # см. комментарий в setup_logging — upgrade() выше сбивает root-логгер

    threading.Thread(target=run_llm_service, args=(llm_port,), daemon=True, name="llm-service").start()
    start_scheduler(app)
    threading.Thread(target=run_backend, args=(app, backend_port), daemon=True, name="backend").start()

    # Токен только в самом первом URL — дальше backend закрепляет его в
    # cookie (см. app/__init__.py: _persist_local_session_cookie), поэтому
    # ни один другой адрес/запрос в приложении токен уже не носит.
    url = f"http://127.0.0.1:{backend_port}/?token={os.environ['AUTOSYNC_SESSION_TOKEN']}"

    # Ждём, пока backend реально начнёт отвечать, прежде чем открывать окно.
    # /api/health — единственный маршрут без проверки токена (см.
    # _require_local_session_token), иначе этот же readiness-запрос сам
    # получал бы 403 и ждал все 30 попыток впустую.
    import urllib.request

    health_url = f"http://127.0.0.1:{backend_port}/api/health"
    for _ in range(30):
        try:
            urllib.request.urlopen(health_url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    logger.info("Открываю окно AutoSync: http://127.0.0.1:%s/", backend_port)
    run_window(url, backend_port=backend_port, session_token=os.environ["AUTOSYNC_SESSION_TOKEN"])

    logger.info("Окно закрыто — завершение работы AutoSync")
    os._exit(0)


if __name__ == "__main__":
    main()
