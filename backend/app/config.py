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


def _default_data_dir() -> str:
    """БД и загрузки: запуск из исходников держит их внутри репозитория
    (data/, см. .gitignore) — не в домашнем каталоге пользователя, чтобы всё
    содержимое проекта оставалось в одном месте. Только у frozen-бинарника
    (см. native_app.py: get_data_dir(), тот же выбор) нет "рядом с исходниками" —
    установленное приложение использует каталог данных ОС."""
    if getattr(sys, "frozen", False):
        return os.path.expanduser("~/.autosync")
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))


class Config:
    """AutoSync — обычное desktop-приложение, без Docker и без серверного
    деплоя: SQLite вместо Postgres, задачи выполняются в самом процессе
    (ThreadPoolExecutor + APScheduler) вместо Celery/Redis, этот же Flask
    отдаёт собранный frontend/dist как статику (нет отдельного nginx).
    Единственная точка входа — окно pywebview (см. native_app.py). Все файлы
    (БД, загрузки) живут в каталоге данных — см. native_app.py: get_data_dir().
    """

    DATA_DIR = os.environ.get("AUTOSYNC_DATA_DIR", _default_data_dir())

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "autosync.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")

    # Подписывает JWT — обязательно переопределить в проде через .env.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JWT_EXPIRES_HOURS = int(os.environ.get("JWT_EXPIRES_HOURS", "168"))  # 7 дней

    # Одноразовый токен на процесс — единственное, что реально не даёт
    # открыть AutoSync обычным браузером по адресу 127.0.0.1 (см.
    # app/__init__.py: _require_local_session_token). Генерируется заново в
    # native_app.py:main() при каждом запуске и передаётся окну через URL —
    # пусто здесь означает "гейт выключен" (тесты, flask db migrate и
    # прочий CLI-запуск не через native_app.py).
    SESSION_TOKEN = os.environ.get("AUTOSYNC_SESSION_TOKEN", "")

    FRONTEND_DIST_DIR = os.environ.get("FRONTEND_DIST_DIR") or _default_frontend_dist_dir()
    MIGRATIONS_DIR = os.environ.get("MIGRATIONS_DIR") or _bundled_resource("migrations")

    LLM_SERVICE_URL = os.environ.get("LLM_SERVICE_URL", "http://127.0.0.1:8001")

    OZON_CLIENT_ID = os.environ.get("OZON_CLIENT_ID", "")
    OZON_API_KEY = os.environ.get("OZON_API_KEY", "")
    OZON_PERFORMANCE_CLIENT_ID = os.environ.get("OZON_PERFORMANCE_CLIENT_ID", "")
    OZON_PERFORMANCE_CLIENT_SECRET = os.environ.get("OZON_PERFORMANCE_CLIENT_SECRET", "")

    ANALYTICS_PROVIDER_BASE_URL = os.environ.get("ANALYTICS_PROVIDER_BASE_URL", "")
    ANALYTICS_PROVIDER_API_KEY = os.environ.get("ANALYTICS_PROVIDER_API_KEY", "")

    PARTS_SUPPLIER_BASE_URL = os.environ.get("PARTS_SUPPLIER_BASE_URL", "")
    PARTS_SUPPLIER_API_KEY = os.environ.get("PARTS_SUPPLIER_API_KEY", "")

    # Пусто по умолчанию — AutoDataClient резолвит нормо-часы через локальный
    # справочник LaborCatalogEntry, пока нет реального доступа к AutoData API.
    AUTODATA_BASE_URL = os.environ.get("AUTODATA_BASE_URL", "")
    AUTODATA_API_KEY = os.environ.get("AUTODATA_API_KEY", "")

    # Пусто по умолчанию — NomenclatureClient ищет по локальной таблице
    # NomenclatureEntry (заполняется загрузкой файла/вручную), пока не
    # подтверждено, откуда у заказчика реально берётся номенклатура/остатки
    # (1С API, отдельная складская система — см. PROJECT.md, «Ограничения»).
    NOMENCLATURE_PROVIDER_BASE_URL = os.environ.get("NOMENCLATURE_PROVIDER_BASE_URL", "")
    NOMENCLATURE_PROVIDER_API_KEY = os.environ.get("NOMENCLATURE_PROVIDER_API_KEY", "")

    # Ниже порога сопоставление обязательно уходит на ручную проверку.
    # TODO: уточнить с заказчиком точное значение.
    MATCH_CONFIDENCE_THRESHOLD = float(os.environ.get("MATCH_CONFIDENCE_THRESHOLD", "0.75"))

    MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB на загружаемые договоры/наряды
