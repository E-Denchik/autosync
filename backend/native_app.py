"""Точка входа для 'обычного приложения' — запуск AutoSync на Windows/Linux
без Docker: backend + llm-service (тонкая обёртка над Ollama) в одном
процессе на двух локальных портах, SQLite вместо Postgres, APScheduler
вместо Celery beat, ThreadPoolExecutor вместо Celery worker (см.
app/config.py: NativeConfig, app/services/job_queue.py).

Открывает браузер на локальный адрес и (если доступна пиктограмма в
трее — pystray) сидит в трее с пунктом «Выход». Логи пишутся в файл
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
    log_path = os.path.join(data_dir, "autosync.log")
    handlers = [logging.FileHandler(log_path, encoding="utf-8")]
    if not is_frozen():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
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
    app = load_llm_service_app()
    logger.info("llm-service слушает на 127.0.0.1:%s", port)
    serve(app, host="127.0.0.1", port=port, _quiet=True)


def run_backend(app, port: int) -> None:
    from waitress import serve

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


def _run_headless_loop(on_quit) -> None:
    logger.info("Работаю без иконки в трее (Ctrl+C для выхода)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        on_quit()


def run_tray(url: str, on_quit) -> None:
    """Иконка в системном трее с пунктами «Открыть» / «Выход». Если pystray
    недоступен (или нет графического окружения — например, установка на
    сервер без GUI) — просто блокируем главный поток, чтобы процесс не
    завершился."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        _run_headless_loop(on_quit)
        return

    def make_icon_image():
        img = Image.new("RGB", (64, 64), "#4f56e6")
        draw = ImageDraw.Draw(img)
        draw.text((14, 20), "AS", fill="white")
        return img

    def _open(_icon, _item):
        webbrowser.open(url)

    def _quit(icon, _item):
        icon.stop()
        on_quit()

    icon = pystray.Icon(
        "autosync",
        make_icon_image(),
        "AutoSync",
        menu=pystray.Menu(
            pystray.MenuItem("Открыть AutoSync", _open, default=True),
            pystray.MenuItem("Выход", _quit),
        ),
    )
    try:
        icon.run()
    except Exception:
        # Нет трея (сервер без GUI, минимальный WM и т.п.) — не роняем
        # приложение, продолжаем работать в фоне.
        logger.warning("Не удалось запустить иконку в трее — работаю в фоне", exc_info=True)
        _run_headless_loop(on_quit)


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
    from app.config import NativeConfig

    app = create_app(NativeConfig)

    with app.app_context():
        from flask_migrate import upgrade

        upgrade()

    threading.Thread(target=run_llm_service, args=(llm_port,), daemon=True, name="llm-service").start()
    start_scheduler(app)
    threading.Thread(target=run_backend, args=(app, backend_port), daemon=True, name="backend").start()

    url = f"http://127.0.0.1:{backend_port}/"

    # Ждём, пока backend реально начнёт отвечать, прежде чем открывать браузер.
    import urllib.request

    for _ in range(30):
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except Exception:
            time.sleep(0.5)

    webbrowser.open(url)
    logger.info("Открываю браузер: %s", url)

    def _on_quit():
        logger.info("Завершение работы AutoSync")
        os._exit(0)

    run_tray(url, _on_quit)


if __name__ == "__main__":
    main()
