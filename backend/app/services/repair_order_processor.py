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
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.autodata_client import AutoDataClient
from app.services.document_parser import (
    DocumentParseError,
    parse_document,
    parse_price_catalog_by_brand,
    parse_repair_order_export,
)
from app.services.history import log_change
from app.services.labor_matcher import match_all_labor, suggest_missing_labor_operations
from app.services.llm_client import LLMClient
from app.services.matcher import match_all
from app.services.nomenclature_client import NomenclatureClient
from app.services.nomenclature_matcher import enrich_all
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
        export = parse_repair_order_export(repair_order.storage_path)
        if export is not None:
            meta = export["meta"]
            repair_order.vehicle_make = repair_order.vehicle_make or meta.get("vehicle_make")
            repair_order.vehicle_model = repair_order.vehicle_model or meta.get("vehicle_model")
            repair_order.vehicle_vin = repair_order.vehicle_vin or meta.get("vehicle_vin")
            repair_order.vehicle_year = repair_order.vehicle_year or meta.get("vehicle_year")
            part_lines = export["part_lines"]
            labor_lines_raw = [
                {"name": l["description"]} for l in export["labor_lines"] if l.get("description")
            ]
            repair_order.parsed_lines = part_lines
        else:
            order_lines = parse_document(repair_order.storage_path)
            repair_order.parsed_lines = order_lines
            part_lines = [line for line in order_lines if line.get("article")]
            labor_lines_raw = [line for line in order_lines if not line.get("article") and line.get("name")]

        catalog_lines = None
        if repair_order.vehicle_make:
            catalog_lines = parse_price_catalog_by_brand(contract.storage_path, repair_order.vehicle_make)
        contract.parsed_lines = catalog_lines if catalog_lines is not None else parse_document(contract.storage_path)
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
        if catalog_lines is not None:
            results = match_all(part_lines, contract.parsed_lines, supplier_client, llm_client)
        else:
            results = match_all(contract.parsed_lines, part_lines, supplier_client, llm_client)
    except Exception as exc:
        logger.exception("match_all упал для repair_order_id=%s", repair_order_id)
        repair_order.status = RepairOrderStatus.FAILED
        repair_order.error_message = f"Ошибка сопоставления: {exc}"
        log_change("repair_order", repair_order.id, "failed", details={"error": str(exc), "stage": "matching"})
        db.session.commit()
        return {"status": "failed", "error": str(exc)}

    # Обогащаем каждое сопоставление данными из внутренней номенклатуры
    # заказчика (код, № кат., производитель, остаток/резерв/склад) — не
    # влияет на confidence_level самого сопоставления, только подтягивает
    # складские метаданные для уже найденной позиции (см. nomenclature_matcher.py).
    # Недоступность источника номенклатуры не должна ронять обработку —
    # тот же принцип, что и для supplier_client/llm_client выше.
    try:
        nomenclature_client = NomenclatureClient(
            current_app.config["NOMENCLATURE_PROVIDER_BASE_URL"],
            current_app.config["NOMENCLATURE_PROVIDER_API_KEY"],
        )
        results = enrich_all(results, nomenclature_client)
    except Exception as exc:
        logger.exception("enrich_all (номенклатура) упал для repair_order_id=%s", repair_order_id)
        log_change("repair_order", repair_order.id, "nomenclature_enrichment_failed", details={"error": str(exc)})

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

    autodata_client = AutoDataClient(
        current_app.config["AUTODATA_BASE_URL"],
        current_app.config["AUTODATA_API_KEY"],
    )
    hourly_rate = float(repair_order.contragent.hourly_rate) if repair_order.contragent else None

    try:
        labor_results = match_all_labor(
            [line["name"] for line in labor_lines_raw],
            repair_order.vehicle_make,
            repair_order.vehicle_model,
            autodata_client,
            llm_client,
        )
    except Exception as exc:
        logger.exception("match_all_labor упал для repair_order_id=%s", repair_order_id)
        labor_results = []
        log_change("repair_order", repair_order.id, "labor_matching_failed", details={"error": str(exc)})

    try:
        suggested_labor = suggest_missing_labor_operations(
            labor_results,
            repair_order.vehicle_make,
            repair_order.vehicle_model,
            autodata_client,
            llm_client,
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
