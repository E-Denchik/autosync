from __future__ import annotations

from app.extensions import db
from app.models import Contract, ContractLaborNorm, ContractPart, DocumentProcessingStatus
from app.services.document_parser import (
    DocumentParseError,
    parse_document_with_ocr_fallback,
    parse_price_catalog_by_brand,
    parse_repair_order_export,
)
from app.services.history import log_change

DOCUMENT_LINE_FIELDS = ["article", "name", "qty", "price"]
BATCH_SIZE = 2000


def _bulk_insert_parts(contract_id: int, lines: list[dict]) -> int:
    rows = [
        {
            "contract_id": contract_id,
            "article": line.get("article"),
            "name": line.get("name"),
            "qty": line.get("qty"),
            "price": line.get("price"),
        }
        for line in lines
        if line.get("name")
    ]
    for i in range(0, len(rows), BATCH_SIZE):
        db.session.bulk_insert_mappings(ContractPart, rows[i : i + BATCH_SIZE])
    return len(rows)


def _bulk_insert_labor_norms(
    contract_id: int, lines: list[dict], vehicle_make: str | None, vehicle_model: str | None
) -> int:
    rows = [
        {
            "contract_id": contract_id,
            "operation_name": line.get("description"),
            "vehicle_make": vehicle_make,
            "vehicle_model": vehicle_model,
            "norm_hours": line.get("norm_hours"),
        }
        for line in lines
        if line.get("description") and line.get("norm_hours") is not None
    ]
    for i in range(0, len(rows), BATCH_SIZE):
        db.session.bulk_insert_mappings(ContractLaborNorm, rows[i : i + BATCH_SIZE])
    return len(rows)


def import_contract_files(contract_id: int, paths: list[str], vehicle_make: str | None, llm_client) -> dict:
    parts_created = 0
    labor_norms_created = 0
    for path in paths:
        export = parse_repair_order_export(path)
        if export is not None:
            parts_created += _bulk_insert_parts(contract_id, export["part_lines"])
            labor_norms_created += _bulk_insert_labor_norms(
                contract_id,
                export["labor_lines"],
                export["meta"].get("vehicle_make") or vehicle_make,
                export["meta"].get("vehicle_model"),
            )
            continue

        lines = parse_price_catalog_by_brand(path, vehicle_make) if vehicle_make else None
        if lines is None:
            lines = parse_document_with_ocr_fallback(path, llm_client, DOCUMENT_LINE_FIELDS)
        parts_created += _bulk_insert_parts(contract_id, lines)

    db.session.commit()
    return {"parts_created": parts_created, "labor_norms_created": labor_norms_created}


def import_contract_job(contract_id: int, paths: list[str], vehicle_make: str | None) -> dict:
    from flask import current_app

    from app.services.llm_client import LLMClient

    contract = db.session.get(Contract, contract_id)
    if not contract:
        return {"status": "failed", "error": "contract not found"}

    contract.status = DocumentProcessingStatus.PARSING
    db.session.commit()

    llm_client = LLMClient(current_app.config["LLM_SERVICE_URL"])
    try:
        result = import_contract_files(contract_id, paths, vehicle_make, llm_client)
    except DocumentParseError as exc:
        contract.status = DocumentProcessingStatus.FAILED
        contract.error_message = str(exc)
        log_change("contract", contract.id, "import_failed", details={"error": str(exc)})
        db.session.commit()
        return {"status": "failed", "error": str(exc)}

    contract.status = DocumentProcessingStatus.PARSED
    contract.error_message = None
    log_change("contract", contract.id, "imported", details=result)
    db.session.commit()
    return {"status": "ok", **result}
