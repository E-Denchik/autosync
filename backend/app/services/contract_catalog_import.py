from __future__ import annotations

import logging
import os

from app.extensions import db
from app.models import (
    Contract,
    ContractHourlyRate,
    ContractLaborNorm,
    ContractPart,
    DocumentProcessingStatus,
    RepairOrder,
)
from app.services.document_parser import (
    DocumentParseError,
    parse_document_with_ocr_fallback,
    parse_price_catalog_by_brand,
    parse_repair_order_export,
)
from app.services.history import log_change

logger = logging.getLogger(__name__)

DOCUMENT_LINE_FIELDS = ["article", "name", "qty", "price"]
BATCH_SIZE = 2000


def _bulk_insert_parts(contract_id: int, lines: list[dict]) -> dict:
    """Пишет строки договора как ContractPart. Позиция с артикулом, который
    в этом договоре уже есть, ОБНОВЛЯЕТСЯ (название/кол-во/цена), а не
    создаётся заново — иначе повторная загрузка того же файла в
    существующий договор (обновлённый прайс, повторная выгрузка того же
    поставщика и т.п.) удваивала бы список запчастей при каждой загрузке.
    У строк без артикула нет естественного ключа — они всегда создаются
    заново (как и раньше)."""
    existing_ids_by_article = {
        p.article: p.id
        for p in ContractPart.query.filter(
            ContractPart.contract_id == contract_id, ContractPart.article.isnot(None)
        ).all()
    }

    to_insert: list[dict] = []
    to_update: list[dict] = []
    index_in_batch: dict[str, int] = {}

    for line in lines:
        if not line.get("name"):
            continue
        article = line.get("article")
        row = {
            "contract_id": contract_id,
            "article": article,
            "name": line.get("name"),
            "qty": line.get("qty"),
            "price": line.get("price"),
        }
        if article and article in existing_ids_by_article:
            to_update.append({**row, "id": existing_ids_by_article[article]})
        elif article and article in index_in_batch:
            # Тот же артикул несколько раз в одном файле — оставляем последнюю строку.
            to_insert[index_in_batch[article]] = row
        else:
            if article:
                index_in_batch[article] = len(to_insert)
            to_insert.append(row)

    for i in range(0, len(to_insert), BATCH_SIZE):
        db.session.bulk_insert_mappings(ContractPart, to_insert[i : i + BATCH_SIZE])
    for i in range(0, len(to_update), BATCH_SIZE):
        db.session.bulk_update_mappings(ContractPart, to_update[i : i + BATCH_SIZE])

    return {"created": len(to_insert), "updated": len(to_update)}


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
    parts_updated = 0
    labor_norms_created = 0
    for path in paths:
        export = parse_repair_order_export(path)
        if export is not None:
            parts_result = _bulk_insert_parts(contract_id, export["part_lines"])
            parts_created += parts_result["created"]
            parts_updated += parts_result["updated"]
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
        parts_result = _bulk_insert_parts(contract_id, lines)
        parts_created += parts_result["created"]
        parts_updated += parts_result["updated"]

    db.session.commit()
    return {"parts_created": parts_created, "parts_updated": parts_updated, "labor_norms_created": labor_norms_created}


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
    except Exception as exc:
        logger.exception("import_contract_files упал для contract_id=%s", contract.id)
        contract.status = DocumentProcessingStatus.FAILED
        contract.error_message = f"Не удалось разобрать договор: {exc}"
        log_change("contract", contract.id, "import_failed", details={"error": str(exc)})
        db.session.commit()
        return {"status": "failed", "error": str(exc)}

    contract.status = DocumentProcessingStatus.PARSED
    contract.error_message = None
    log_change("contract", contract.id, "imported", details=result)
    db.session.commit()
    return {"status": "ok", **result}


class ContractMergeError(RuntimeError):
    pass


def merge_contracts(source_id: int, target_id: int) -> dict:
    """Склеивает два договора: заказ-наряды и уникальные позиции source
    переезжают на target, затем опустевший source удаляется. Для ручной
    уборки случайно задвоившихся договоров (см. app/api/contracts.py) —
    content_hash в create_contract()/upload.py не даёт им плодиться
    дальше, но уже существующие дубликаты нужно свести руками.

    Позиции (запчасти/нормо-часы/ставки), которые по естественному ключу
    уже есть в target, НЕ переносятся — остаются на source и удаляются
    вместе с ним каскадом: данные target считаются приоритетными, тем же
    принципом, что и повторный импорт в один договор (см. _bulk_insert_parts)."""
    if source_id == target_id:
        raise ContractMergeError("Нельзя объединить договор сам с собой")
    source = db.session.get(Contract, source_id)
    target = db.session.get(Contract, target_id)
    if source is None or target is None:
        raise ContractMergeError("Один из договоров не найден")

    repair_orders_moved = RepairOrder.query.filter_by(contract_id=source.id).update(
        {"contract_id": target.id}, synchronize_session=False
    )

    target_articles = {
        row[0]
        for row in db.session.query(ContractPart.article)
        .filter(ContractPart.contract_id == target.id, ContractPart.article.isnot(None))
        .all()
    }
    parts_to_move = [
        p.id
        for p in ContractPart.query.filter_by(contract_id=source.id).all()
        if p.article is None or p.article not in target_articles
    ]
    parts_moved = 0
    if parts_to_move:
        parts_moved = ContractPart.query.filter(ContractPart.id.in_(parts_to_move)).update(
            {"contract_id": target.id}, synchronize_session=False
        )

    target_norm_keys = {
        (n.operation_name, n.vehicle_make, n.vehicle_model)
        for n in ContractLaborNorm.query.filter_by(contract_id=target.id).all()
    }
    norms_to_move = [
        n.id
        for n in ContractLaborNorm.query.filter_by(contract_id=source.id).all()
        if (n.operation_name, n.vehicle_make, n.vehicle_model) not in target_norm_keys
    ]
    labor_norms_moved = 0
    if norms_to_move:
        labor_norms_moved = ContractLaborNorm.query.filter(ContractLaborNorm.id.in_(norms_to_move)).update(
            {"contract_id": target.id}, synchronize_session=False
        )

    target_hourly_makes = {
        r.vehicle_make for r in ContractHourlyRate.query.filter_by(contract_id=target.id).all()
    }
    rates_to_move = [
        r.id
        for r in ContractHourlyRate.query.filter_by(contract_id=source.id).all()
        if r.vehicle_make not in target_hourly_makes
    ]
    hourly_rates_moved = 0
    if rates_to_move:
        hourly_rates_moved = ContractHourlyRate.query.filter(ContractHourlyRate.id.in_(rates_to_move)).update(
            {"contract_id": target.id}, synchronize_session=False
        )

    source_paths = [source.storage_path] + [f.storage_path for f in source.extra_files]

    result = {
        "repair_orders_moved": repair_orders_moved,
        "parts_moved": parts_moved,
        "labor_norms_moved": labor_norms_moved,
        "hourly_rates_moved": hourly_rates_moved,
    }
    log_change(
        "contract",
        target.id,
        "merged_from",
        details={"source_contract_id": source.id, "source_name": source.name or source.original_filename, **result},
    )

    db.session.delete(source)
    db.session.commit()

    for path in source_paths:
        if os.path.isfile(path):
            os.remove(path)

    return result
