"""Бизнес-логика обработки загруженного заказ-наряда: парсинг файла,
сопоставление позиций с каталогом контракта (см. services/matcher.py,
services/contract_catalog_import.py).

Вызывается из ThreadPoolExecutor (см. services/job_queue.py) — единственное
требование вызывающей стороны: выполнять внутри app_context().
"""

from __future__ import annotations

import logging

from flask import current_app

from app.extensions import db
from app.models import (
    Contract,
    ContractLaborNorm,
    DocumentProcessingStatus,
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.autodata_client import AutoDataClient
from app.services.contract_catalog_import import import_contract_files
from app.services.document_parser import DocumentParseError, parse_document_with_ocr_fallback, parse_repair_order_export
from app.services.history import log_change
from app.services.labor_matcher import (
    match_all_labor,
    match_all_labor_against_contract,
    suggest_missing_labor_operations,
    suggest_missing_labor_operations_from_contract,
)
from app.services.llm_client import LLMClient
from app.services.matcher import match_all_against_contract
from app.services.nomenclature_client import NomenclatureClient
from app.services.nomenclature_matcher import enrich_all
from app.services.parts_supplier_client import PartsSupplierClient

logger = logging.getLogger(__name__)

DOCUMENT_LINE_FIELDS = ["article", "name", "qty", "price"]


def _repair_order_paths(repair_order: RepairOrder) -> list[str]:
    return [repair_order.storage_path] + [f.storage_path for f in repair_order.extra_files]


def _contract_paths(contract: Contract) -> list[str]:
    return [contract.storage_path] + [f.storage_path for f in contract.extra_files]


def _parse_repair_order_files(paths: list[str], llm_client: LLMClient) -> tuple[dict, list[dict], list[dict]]:
    meta = {"vehicle_make": None, "vehicle_model": None, "vehicle_vin": None, "vehicle_year": None}
    part_lines: list[dict] = []
    labor_lines_raw: list[dict] = []
    for path in paths:
        export = parse_repair_order_export(path)
        if export is not None:
            for key in meta:
                meta[key] = meta[key] or export["meta"].get(key)
            part_lines.extend(export["part_lines"])
            labor_lines_raw.extend(
                {"name": l["description"]} for l in export["labor_lines"] if l.get("description")
            )
        else:
            order_lines = parse_document_with_ocr_fallback(path, llm_client, DOCUMENT_LINE_FIELDS)
            part_lines.extend(line for line in order_lines if line.get("article"))
            labor_lines_raw.extend(
                line for line in order_lines if not line.get("article") and line.get("name")
            )
    return meta, part_lines, labor_lines_raw


def process_upload_job(contract_id: int, repair_order_id: int) -> dict:
    contract = db.session.get(Contract, contract_id)
    repair_order = db.session.get(RepairOrder, repair_order_id)
    if not contract or not repair_order:
        return {"status": "failed", "error": "contract or repair_order not found"}

    repair_order.status = RepairOrderStatus.PARSING
    db.session.commit()

    llm_client = LLMClient(current_app.config["LLM_SERVICE_URL"])

    try:
        meta, part_lines, labor_lines_raw = _parse_repair_order_files(
            _repair_order_paths(repair_order), llm_client
        )
        repair_order.vehicle_make = repair_order.vehicle_make or meta.get("vehicle_make")
        repair_order.vehicle_model = repair_order.vehicle_model or meta.get("vehicle_model")
        repair_order.vehicle_vin = repair_order.vehicle_vin or meta.get("vehicle_vin")
        repair_order.vehicle_year = repair_order.vehicle_year or meta.get("vehicle_year")
        repair_order.parsed_lines = part_lines
    except DocumentParseError as exc:
        message = f"Не удалось прочитать заказ-наряд: {exc}"
        repair_order.status = RepairOrderStatus.FAILED
        repair_order.error_message = message
        log_change("repair_order", repair_order.id, "failed", details={"error": message, "stage": "parsing"})
        db.session.commit()
        return {"status": "failed", "error": message}

    if contract.status != DocumentProcessingStatus.PARSED:
        contract.status = DocumentProcessingStatus.PARSING
        db.session.commit()
        try:
            import_contract_files(contract.id, _contract_paths(contract), repair_order.vehicle_make, llm_client)
        except DocumentParseError as exc:
            message = (
                f"Не удалось прочитать договор: {exc}. Ожидается либо прайс-лист "
                "с колонками артикул/наименование/цена, либо каталог цен по маркам, "
                "либо экспорт заказ-наряда с разделами работ/материалов."
            )
            contract.status = DocumentProcessingStatus.FAILED
            contract.error_message = message
            repair_order.status = RepairOrderStatus.FAILED
            repair_order.error_message = message
            log_change("repair_order", repair_order.id, "failed", details={"error": message, "stage": "parsing"})
            db.session.commit()
            return {"status": "failed", "error": message}
        contract.status = DocumentProcessingStatus.PARSED
        contract.error_message = None

    repair_order.status = RepairOrderStatus.MATCHING
    db.session.commit()

    supplier_client = PartsSupplierClient(
        current_app.config["PARTS_SUPPLIER_BASE_URL"],
        current_app.config["PARTS_SUPPLIER_API_KEY"],
    )

    try:
        results = match_all_against_contract(part_lines, contract.id, supplier_client, llm_client)
    except Exception as exc:
        logger.exception("match_all_against_contract упал для repair_order_id=%s", repair_order_id)
        repair_order.status = RepairOrderStatus.FAILED
        repair_order.error_message = f"Ошибка сопоставления: {exc}"
        log_change("repair_order", repair_order.id, "failed", details={"error": str(exc), "stage": "matching"})
        db.session.commit()
        return {"status": "failed", "error": str(exc)}

    try:
        nomenclature_client = NomenclatureClient(
            current_app.config["ALFAAUTO_BASE_URL"],
            current_app.config["ALFAAUTO_LOGIN"],
            current_app.config["ALFAAUTO_PASSWORD"],
        )
        results = enrich_all(results, nomenclature_client)
    except Exception as exc:
        logger.exception("enrich_all (номенклатура) упал для repair_order_id=%s", repair_order_id)
        log_change("repair_order", repair_order.id, "nomenclature_enrichment_failed", details={"error": str(exc)})

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

    hourly_rate = float(repair_order.contragent.hourly_rate) if repair_order.contragent else None
    has_contract_labor_norms = ContractLaborNorm.query.filter_by(contract_id=contract.id).first() is not None
    descriptions = [line["name"] for line in labor_lines_raw]

    try:
        if has_contract_labor_norms:
            labor_results = match_all_labor_against_contract(
                descriptions, contract.id, repair_order.vehicle_make, repair_order.vehicle_model, llm_client
            )
        else:
            autodata_client = AutoDataClient(
                current_app.config["ALFAAUTO_BASE_URL"],
                current_app.config["ALFAAUTO_LOGIN"],
                current_app.config["ALFAAUTO_PASSWORD"],
            )
            labor_results = match_all_labor(
                descriptions, repair_order.vehicle_make, repair_order.vehicle_model, autodata_client, llm_client
            )
    except Exception as exc:
        logger.exception("сопоставление работ упало для repair_order_id=%s", repair_order_id)
        labor_results = []
        log_change("repair_order", repair_order.id, "labor_matching_failed", details={"error": str(exc)})

    try:
        if has_contract_labor_norms:
            suggested_labor = suggest_missing_labor_operations_from_contract(
                labor_results, contract.id, repair_order.vehicle_make, repair_order.vehicle_model, llm_client
            )
        else:
            autodata_client = AutoDataClient(
                current_app.config["ALFAAUTO_BASE_URL"],
                current_app.config["ALFAAUTO_LOGIN"],
                current_app.config["ALFAAUTO_PASSWORD"],
            )
            suggested_labor = suggest_missing_labor_operations(
                labor_results, repair_order.vehicle_make, repair_order.vehicle_model, autodata_client, llm_client
            )
    except Exception as exc:
        logger.exception("suggest_missing_labor_operations упал для repair_order_id=%s", repair_order_id)
        suggested_labor = []
    labor_results = labor_results + suggested_labor

    for result in labor_results:
        norm_hours = result.get("norm_hours")
        total_cost = norm_hours * hourly_rate if norm_hours is not None and hourly_rate is not None else None
        labor_line = LaborLine(
            repair_order_id=repair_order.id,
            hourly_rate=hourly_rate,
            total_cost=total_cost,
            **result,
        )
        db.session.add(labor_line)
        db.session.flush()
        log_change(
            "labor_line",
            labor_line.id,
            "created",
            details={"confidence_level": labor_line.confidence_level.value, "source": "auto-match"},
        )

    repair_order.status = RepairOrderStatus.NEEDS_REVIEW
    log_change(
        "repair_order",
        repair_order.id,
        "needs_review",
        details={"matches_created": len(results), "labor_lines_created": len(labor_results)},
    )
    db.session.commit()

    return {"status": "ok", "matches_created": len(results), "labor_lines_created": len(labor_results)}
