"""Единая точка постановки асинхронных задач в очередь — прячет разницу
между двумя режимами запуска:

- docker-compose (Config.USE_CELERY=True): реальная очередь на Celery/Redis,
  задачу подхватывает отдельный celery-worker процесс;
- native (NativeConfig.USE_CELERY=False): задача выполняется в
  ThreadPoolExecutor внутри того же процесса — отдельного воркера/брокера
  нет и не нужно, всё приложение — один процесс.

API-роуты вызывают только функции из этого модуля и не знают, какой режим
активен — см. api/repair_orders/upload.py.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from flask import current_app

# Импортируем на уровне модуля, а не лениво внутри воркер-потока: в
# PyInstaller-сборке первый импорт модуля из НЕ-главного потока иногда
# заканчивается тихо (без исключения, без результата) — рантайм-хуки
# PyInstaller для importlib рассчитаны на импорт из главного потока при
# старте. К моменту, когда этот файл вообще импортируют (первый апload),
# приложение уже полностью инициализировано, так что импортировать здесь
# безопасно и в docker/dev-режиме тоже.
from app.services.repair_order_processor import process_upload_job

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="autosync-job")


def enqueue_process_upload(contract_id: int, repair_order_id: int) -> None:
    if current_app.config["USE_CELERY"]:
        from app.tasks.process_upload import process_upload

        process_upload.delay(contract_id, repair_order_id)
        return

    app = current_app._get_current_object()

    def _run():
        with app.app_context():
            try:
                process_upload_job(contract_id, repair_order_id)
            except Exception:
                logger.exception(
                    "process_upload_job упал для contract_id=%s repair_order_id=%s",
                    contract_id,
                    repair_order_id,
                )

    _executor.submit(_run)
