import os


class Config:
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql://autosync:autosync@localhost:5432/autosync"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

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
