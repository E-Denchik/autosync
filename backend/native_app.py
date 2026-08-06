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
import sys
import threading
import time
import webbrowser

logger = logging.getLogger("autosync.native")

if sys.platform.startswith("linux"):
    # WebKitGTK's DMA-BUF renderer сегфолтит на части систем без полноценного
    # GPU-доступа (виртуалки, некоторые песочницы/контейнеры, старые драйверы
    # Mesa) — без этого флага окно может не открыться вовсе. Программный
    # рендеринг чуть медленнее, но для админ-панели это не критично.
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")

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


def get_data_dir() -> str:
    override = os.environ.get("AUTOSYNC_DATA_DIR")
    if override:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "AutoSync")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/AutoSync")
    return os.path.expanduser("~/.autosync")


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
    from app.services.price_sync import sync_ozon_prices_job

    def _sync_job():
        with app.app_context():
            try:
                sync_ozon_prices_job()
            except Exception:
                logger.exception("sync_ozon_prices_job упал")

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_sync_job, "interval", hours=6, id="sync_ozon_prices", next_run_time=None)
    scheduler.start()
    return scheduler


def _run_headless_loop() -> None:
    """Резервный режим, когда системное окно поднять не удалось (нет
    WebView2/WebKitGTK, headless-сервер и т.п.) — уже открыт браузер,
    просто не даём процессу завершиться до Ctrl+C."""
    logger.info("Нет доступного системного окна — работаю в фоне (Ctrl+C для выхода)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def run_window(url: str) -> None:
    """Открывает AutoSync в собственном окне через pywebview (системный
    webview — WebView2 на Windows, WebKitGTK на Linux, без Chromium внутри
    приложения). Закрытие окна — единственная точка выхода, полностью
    завершает процесс (см. main()): фоновые задачи (плановый синк цен)
    не переживают закрытие окна, это осознанный выбор ради простоты — одно
    окно, один процесс, без иконки в трее и скрытого фонового режима.

    Если системный webview недоступен (сломанная установка WebView2,
    отсутствующий webkit2gtk на Linux без десктопного окружения) — не
    роняем приложение, откатываемся на браузер по умолчанию."""
    try:
        import webview
    except Exception:
        logger.warning("pywebview недоступен — открываю в браузере по умолчанию", exc_info=True)
        webbrowser.open(url)
        _run_headless_loop()
        return

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

    webview.create_window(
        "AutoSync", url, width=width, height=height, min_size=(1024, 700), maximized=True
    )
    try:
        # private_mode=False — по умолчанию pywebview открывает окно как
        # приватную/инкогнито-сессию: WebKitGTK создаёт эфемерный контекст
        # и явно выключает HTML5 localStorage (см. platforms/gtk.py). Наш
        # AuthContext хранит JWT в localStorage и трогает его на каждом
        # старте, если пользователь уже создан — с private_mode по
        # умолчанию это падает необработанным исключением ДО того, как
        # выставляется loading=false, и окно виснет на "Загрузка..."
        # навсегда при каждом запуске после первого /setup. Обнаружено
        # только сквозным ручным тестированием окна — с пустой БД (мастер
        # /setup, localStorage ещё не трогали) баг незаметен.
        webview.start(private_mode=False)
    except Exception:
        logger.warning("Не удалось открыть системное окно — открываю в браузере по умолчанию", exc_info=True)
        webbrowser.open(url)
        _run_headless_loop()


def main() -> None:
    data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "uploads"), exist_ok=True)
    os.environ["AUTOSYNC_DATA_DIR"] = data_dir

    setup_logging(data_dir)
    logger.info("AutoSync запускается, каталог данных: %s", data_dir)

    backend_port = int(os.environ.get("AUTOSYNC_PORT", "5000"))
    llm_port = int(os.environ.get("AUTOSYNC_LLM_PORT", "8001"))
    os.environ.setdefault("LLM_SERVICE_URL", f"http://127.0.0.1:{llm_port}")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from app import create_app

    app = create_app()

    with app.app_context():
        from flask_migrate import upgrade

        upgrade()

    setup_logging(data_dir)  # см. комментарий в setup_logging — upgrade() выше сбивает root-логгер

    threading.Thread(target=run_llm_service, args=(llm_port,), daemon=True, name="llm-service").start()
    start_scheduler(app)
    threading.Thread(target=run_backend, args=(app, backend_port), daemon=True, name="backend").start()

    url = f"http://127.0.0.1:{backend_port}/"

    # Ждём, пока backend реально начнёт отвечать, прежде чем открывать окно.
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    logger.info("Открываю окно AutoSync: %s", url)
    run_window(url)

    logger.info("Окно закрыто — завершение работы AutoSync")
    os._exit(0)


if __name__ == "__main__":
    main()
