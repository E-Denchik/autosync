"""Постановка асинхронной обработки загруженного файла в фон —
ThreadPoolExecutor внутри того же процесса, отдельного воркера/брокера нет
и не нужно, всё приложение — один процесс (см. native_app.py).

API-роуты вызывают только эту функцию — см. api/repair_orders/upload.py.
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
# безопасно.
from app.services.repair_order_processor import process_upload_job

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="autosync-job")


def enqueue_process_upload(contract_id: int, repair_order_id: int) -> None:
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
