"""Асинхронная обработка загруженных договора + заказ-наряда:
парсинг обоих файлов, сопоставление позиций (см. services/matcher.py).
"""

from __future__ import annotations

from flask import current_app

from app.extensions import celery, db
from app.models import (
    Contract,
    DocumentProcessingStatus,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.document_parser import DocumentParseError, parse_document
from app.services.llm_client import LLMClient
from app.services.matcher import match_all
from app.services.parts_supplier_client import PartsSupplierClient


@celery.task(name="tasks.process_upload")
def process_upload(contract_id: int, repair_order_id: int):
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

    results = match_all(contract.parsed_lines, repair_order.parsed_lines, supplier_client, llm_client)

    # Все сопоставления создаются со статусом PENDING (см. модель PartMatch) —
    # ReviewMatches сортирует/подсвечивает low-confidence позиции на фронте,
    # но ни одна не применяется без явного approve человеком.
    for result in results:
        db.session.add(PartMatch(repair_order_id=repair_order.id, **result))

    repair_order.status = RepairOrderStatus.NEEDS_REVIEW
    db.session.commit()

    return {"status": "ok", "matches_created": len(results)}
