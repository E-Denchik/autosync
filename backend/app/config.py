import os
import sys


def _bundled_resource(*relative_to_backend: str) -> str:
    """Путь к ресурсу, упакованному вместе с приложением: либо рядом с
    исходниками backend/ (обычный запуск), либо внутри временной папки
    PyInstaller (frozen-бинарник, см. scripts/build-native.sh)."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))  # backend/
    return os.path.join(base, *relative_to_backend)


def _default_frontend_dist_dir() -> str:
    if getattr(sys, "frozen", False):
        return _bundled_resource("frontend_dist")
    # Запуск из исходников (python native_app.py) — dist лежит рядом с backend/.
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://autosync:autosync@localhost:5432/autosync"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Подписывает JWT — обязательно переопределить в проде через .env.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "168"))  # 7 дней

    # True — асинхронные задачи (обработка загрузок, синк цен) идут через
    # Celery/Redis (docker-compose режим). False — через ThreadPoolExecutor
    # и APScheduler в одном процессе (native-режим, см. NativeConfig).
    USE_CELERY = True
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

    # Отдавать ли собранный frontend/dist прямо из Flask (native-режим —
    # там нет отдельного nginx-контейнера). В docker-compose режиме — False,
    # фронт раздаёт свой nginx-контейнер.
    SERVE_FRONTEND = False

    LLM_SERVICE_URL = os.environ.get("LLM_SERVICE_URL", "http://localhost:8000")

    OZON_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
    OZON_API_KEY = os.environ.get("OZON_API_KEY", "")
    OZON_PERFORMANCE_CLIENT_ID = os.environ.get("OZON_PERFORMANCE_CLIENT_ID", "")
    OZON_PERFORMANCE_CLIENT_SECRET = os.environ.get("OZON_PERFORMANCE_CLIENT_SECRET", "")

    ANALYTICS_PROVIDER_BASE_URL = os.environ.get("ANALYTICS_PROVIDER_BASE_URL", "")
    ANALYTICS_PROVIDER_API_KEY = os.environ.get("ANALYTICS_PROVIDER_API_KEY", "")

    PARTS_SUPPLIER_BASE_URL = os.environ.get("PARTS_SUPPLIER_BASE_URL", "")
    PARTS_SUPPLIER_API_KEY = os.environ.get("PARTS_SUPPLIER_API_KEY", "")

    # Ниже порога сопоставление обязательно уходит на ручную проверку.
    # TODO: уточнить с заказчиком точное значение.
    MATCH_CONFIDENCE_THRESHOLD = float(os.environ.get("MATCH_CONFIDENCE_THRESHOLD", "0.75"))

    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/autosync-uploads")

    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB на загружаемые договоры/наряды

    # None — Flask-Migrate использует свою стандартную папку 'migrations'
    # рядом с местом запуска. NativeConfig переопределяет абсолютным путём,
    # т.к. в frozen-бинарнике текущая директория непредсказуема.
    MIGRATIONS_DIR = None


class NativeConfig(Config):
    """Однопроцессный запуск без Docker — 'обычное приложение' на Windows/Linux.

    SQLite вместо Postgres (не нужен отдельный сервер БД), задачи выполняются
    в самом процессе (ThreadPoolExecutor + APScheduler) вместо Celery/Redis.
    Все файлы (БД, загрузки) живут в одном каталоге данных пользователя —
    см. native_app.py: get_data_dir().
    """

    DATA_DIR = os.environ.get("AUTOSYNC_DATA_DIR", os.path.expanduser("~/.autosync"))

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "autosync.db")
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

    USE_CELERY = False
    SERVE_FRONTEND = True
    FRONTEND_DIST_DIR = os.environ.get("FRONTEND_DIST_DIR") or _default_frontend_dist_dir()
    MIGRATIONS_DIR = os.environ.get("MIGRATIONS_DIR") or _bundled_resource("migrations")

    LLM_SERVICE_URL = os.environ.get("LLM_SERVICE_URL", "http://127.0.0.1:8001")
