"""Celery-обёртка над sync_ozon_prices_job — используется только в
docker-compose режиме (USE_CELERY=True, вызывается celery beat). См.
services/price_sync.py для самой логики."""

from app.extensions import celery
from app.services.price_sync import sync_ozon_prices_job


@celery.task(name="tasks.sync_ozon_prices")
def sync_ozon_prices():
    return sync_ozon_prices_job()
