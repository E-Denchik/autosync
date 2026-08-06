"""Бизнес-логика обработки загруженного договора + заказ-наряда: парсинг
обоих файлов, сопоставление позиций (см. services/matcher.py).

Вызывается из ThreadPoolExecutor (см. services/job_queue.py) — единственное
требование вызывающей стороны: выполнять внутри app_context().
"""

from __future__ import annotations

import logging

from flask import current_app

from app.extensions import db
from app.models import (
    Contract,
    DocumentProcessingStatus,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.document_parser import DocumentParseError, parse_document
from app.services.history import log_change
from app.services.llm_client import LLMClient
from app.services.matcher import match_all
from app.services.parts_supplier_client import PartsSupplierClient

logger = logging.getLogger(__name__)


def process_upload_job(contract_id: int, repair_order_id: int) -> dict:
    contract = db.session.get(Contract, contract_id)
    repair_order = db.session.get(RepairOrder, repair_order_id)
    if not contract or not repair_order:
        return {"status": "failed", "error": "contract or repair_order not found"}

    contract.status = DocumentProcessingStatus.PARSING
    repair_order.status = RepairOrderStatus.PARSING
    db.session.commit()

    try:
        contract.parsed_lines = parse_document(contract.storage_path)
        repair_order.parsed_lines = parse_document(repair_order.storage_path)
    except DocumentParseError as exc:
        contract.status = DocumentProcessingStatus.FAILED
        repair_order.status = RepairOrderStatus.FAILED
        repair_order.error_message = str(exc)
        log_change("repair_order", repair_order.id, "failed", details={"error": str(exc), "stage": "parsing"})
        db.session.commit()
        return {"status": "failed", "error": str(exc)}

    contract.status = DocumentProcessingStatus.PARSED
    repair_order.status = RepairOrderStatus.MATCHING
    db.session.commit()

    supplier_client = PartsSupplierClient(
        current_app.config["PARTS_SUPPLIER_BASE_URL"],
        current_app.config["PARTS_SUPPLIER_API_KEY"],
    )
    llm_client = LLMClient(current_app.config["LLM_SERVICE_URL"])

    try:
        results = match_all(contract.parsed_lines, repair_order.parsed_lines, supplier_client, llm_client)
    except Exception as exc:
        # Подстраховка на случай непредвиденной ошибки сопоставления —
        # без этого заказ-наряд зависает в статусе "matching" навсегда,
        # ничего не сообщая пользователю (см. matcher.py — там уже есть
        # защита от ошибок самой LLM, это доп. уровень на случай прочего).
        logger.exception("match_all упал для repair_order_id=%s", repair_order_id)
        repair_order.status = RepairOrderStatus.FAILED
        repair_order.error_message = f"Ошибка сопоставления: {exc}"
        log_change("repair_order", repair_order.id, "failed", details={"error": str(exc), "stage": "matching"})
        db.session.commit()
        return {"status": "failed", "error": str(exc)}

    # Все сопоставления создаются со статусом PENDING (см. модель PartMatch) —
    # ReviewMatches сортирует/подсвечивает low-confidence позиции на фронте,
    # но ни одна не применяется без явного approve человеком.
    for result in results:
        match = PartMatch(repair_order_id=repair_order.id, **result)
        db.session.add(match)
        db.session.flush()
        log_change(
            "part_match",
            match.id,
            "created",
            details={"confidence_level": match.confidence_level.value, "source": "auto-match"},
        )

    repair_order.status = RepairOrderStatus.NEEDS_REVIEW
    log_change("repair_order", repair_order.id, "needs_review", details={"matches_created": len(results)})
    db.session.commit()

    return {"status": "ok", "matches_created": len(results)}
