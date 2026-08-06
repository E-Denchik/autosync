"""Celery-обёртка над process_upload_job — используется только в
docker-compose режиме (USE_CELERY=True). См. services/repair_order_processor.py
для самой логики и services/job_queue.py для выбора между Celery и потоками."""

from app.extensions import celery
from app.services.repair_order_processor import process_upload_job


@celery.task(name="tasks.process_upload")
def process_upload(contract_id: int, repair_order_id: int):
    return process_upload_job(contract_id, repair_order_id)
