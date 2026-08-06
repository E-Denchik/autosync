"""Entrypoint для Celery worker/beat: `celery -A celery_worker.celery worker`."""

from app import create_app
from app.extensions import celery

flask_app = create_app()

from app.tasks import sync_ozon_prices, process_upload  # noqa: E402,F401

celery.conf.beat_schedule = {
    "sync-ozon-prices-every-6-hours": {
        "task": "tasks.sync_ozon_prices",
        "schedule": 6 * 60 * 60,
    },
}
