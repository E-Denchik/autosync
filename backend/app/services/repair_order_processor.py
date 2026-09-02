"""Бизнес-логика обработки загруженного заказ-наряда: парсинг файла,
сопоставление позиций с каталогом контракта (см. services/matcher.py,
services/contract_catalog_import.py).

Вызывается из ThreadPoolExecutor (см. services/job_queue.py) — единственное
требование вызывающей стороны: выполнять внутри app_context().
"""

from __future__ import annotations

import logging
from collections import Counter

from flask import current_app

from app.extensions import db
from app.models import (
    Contract,
    ContractHourlyRate,
    ContractLaborNorm,
    ContragentHourlyRate,
    DocumentProcessingStatus,
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
)
from app.services.autodata_client import AutoDataClient
from app.services.brand_normalizer import normalize_brand_with_ai_fallback
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
from app.services.parts_supplier_client import build_configured_supplier_client
from app.services.raw_import_staging import mark_rows_moved, stage_raw_rows

logger = logging.getLogger(__name__)

DOCUMENT_LINE_FIELDS = ["article", "name", "qty", "price"]


def _repair_order_paths(repair_order: RepairOrder) -> list[str]:
    return [repair_order.storage_path] + [f.storage_path for f in repair_order.extra_files]


def _contract_paths(contract: Contract) -> list[str]:
    return [contract.storage_path] + [f.storage_path for f in contract.extra_files]


def _find_hourly_rate(model_cls, fk_field: str, fk_value: int, vehicle_make: str, vehicle_model: str | None):
    """Ставка за нормо-час по марке (+ опционально модели) — регистронезависимо
    (марка из заказ-наряда обычно ЗАГЛАВНЫМИ из 1С-выгрузки, ставку заводят
    вручную/из файла как угодно — см. ContractHourlyRate.vehicle_model).
    Реальный тендерный прайс заказчика даёт РАЗНЫЕ ставки для разных
    моделей одной марки (Hyundai Accent — 720 ₽, Hyundai Tucson/IX35 —
    810 ₽) — точное совпадение по модели проверяется первым, ставка "на
    все модели марки" (vehicle_model IS NULL) — запасной вариант."""
    query = model_cls.query.filter(
        getattr(model_cls, fk_field) == fk_value,
        db.func.lower(model_cls.vehicle_make) == vehicle_make.lower(),
    )
    if vehicle_model:
        exact = query.filter(db.func.lower(model_cls.vehicle_model) == vehicle_model.lower()).first()
        if exact is not None:
            return exact
    return query.filter(model_cls.vehicle_model.is_(None)).first()


def resolve_hourly_rate(repair_order: RepairOrder) -> float | None:
    """Ставка за нормо-час для заказ-наряда: сначала по марке+модели в самом
    договоре, затем по марке+модели у контрагента (общей, вне привязки к
    конкретному договору), затем — общая ставка контрагента. Общая логика
    для автосопоставления (process_upload_job) и для ручного добавления
    строки работ (см. app/api/repair_orders/labor.py::add_labor_line)."""
    contract_rate = None
    contragent_make_rate = None
    if repair_order.vehicle_make and repair_order.contract_id:
        contract_rate = _find_hourly_rate(
            ContractHourlyRate, "contract_id", repair_order.contract_id, repair_order.vehicle_make, repair_order.vehicle_model
        )
        if contract_rate is None and repair_order.contragent:
            contragent_make_rate = _find_hourly_rate(
                ContragentHourlyRate,
                "contragent_id",
                repair_order.contragent.id,
                repair_order.vehicle_make,
                repair_order.vehicle_model,
            )
    if contract_rate is not None:
        return float(contract_rate.hourly_rate)
    if contragent_make_rate is not None:
        return float(contragent_make_rate.hourly_rate)
    return float(repair_order.contragent.hourly_rate) if repair_order.contragent else None


def _parse_one_repair_order_file(path: str, llm_client: LLMClient) -> dict:
    """Разбирает ОДИН приложенный файл заказ-наряда, ничего не пишет в БД —
    тот же контракт, что и contract_catalog_import._parse_one_contract_file,
    и по той же причине: это делает разбор нескольких файлов безопасным для
    параллельного выполнения (см. _parse_repair_order_files ниже)."""
    export = parse_repair_order_export(path)
    if export is not None:
        return {"kind": "export", "export": export}
    order_lines = parse_document_with_ocr_fallback(path, llm_client, DOCUMENT_LINE_FIELDS)
    return {"kind": "order_lines", "order_lines": order_lines}


def _parse_repair_order_files(paths: list[str], llm_client: LLMClient) -> tuple[dict, list[dict], list[dict]]:
    """Несколько приложенных файлов ОДНОГО заказ-наряда (см. "Добавить ещё
    файлы") раньше разбирались строго по одному, хотя разбор каждого файла
    независим и настолько же может упереться в OCR/LLM-фоллбэк, как и файлы
    каталога договора — см. contract_catalog_import.import_contract_files,
    где ровно эта же проблема уже была исправлена тем же приёмом (несколько
    файлов заказ-наряда — редкость по сравнению с сотнями файлов каталога,
    но алгоритм должен быть одинаков для обоих мест, а не только для одного).

    Слияние meta/part_lines/labor_lines_raw остаётся строго последовательным
    и в исходном порядке paths (map_with_app_context его сохраняет) — важно
    для meta: "первое непустое значение побеждает" должно быть первым по
    порядку файлов, а не по порядку завершения потоков."""
    from app.services.parallel import llm_workers, map_with_app_context

    parsed = map_with_app_context(
        lambda path: _parse_one_repair_order_file(path, llm_client),
        paths,
        max_workers=llm_workers(),
    )

    meta = {
        "order_number": None,
        "order_date": None,
        "vehicle_make": None,
        "vehicle_model": None,
        "vehicle_vin": None,
        "vehicle_year": None,
    }
    part_lines: list[dict] = []
    labor_lines_raw: list[dict] = []
    for item in parsed:
        if item["kind"] == "export":
            export = item["export"]
            for key in meta:
                meta[key] = meta[key] or export["meta"].get(key)
            part_lines.extend(export["part_lines"])
            labor_lines_raw.extend(
                {"name": l["description"], "source_norm_hours": l.get("norm_hours")}
                for l in export["labor_lines"]
                if l.get("description")
            )
        else:
            order_lines = item["order_lines"]
            part_lines.extend(line for line in order_lines if line.get("article"))
            labor_lines_raw.extend(
                line for line in order_lines if not line.get("article") and line.get("name")
            )
    return meta, part_lines, labor_lines_raw


def _generate_review_summary(
    repair_order: RepairOrder, results: list[dict], labor_results: list[dict], llm_client: LLMClient
) -> str | None:
    """Короткая AI-сводка "на что смотреть в первую очередь" на странице
    проверки — считается один раз сразу после сопоставления, по уже
    готовым results/labor_results (см. process_upload_job), не отдельным
    запросом по требованию. Возвращает None, если сводок нечего строить
    (пустой заказ-наряд) или сама генерация не удалась — это не должно
    ронять обработку заказ-наряда целиком, просто панель на странице
    проверки останется без сводки."""
    if not results and not labor_results:
        return None

    parts_by_source = Counter((r.get("raw_match_data") or {}).get("source") for r in results)
    labor_by_source = Counter((r.get("raw_match_data") or {}).get("source") for r in labor_results)

    stats = {
        "vehicle_make": repair_order.vehicle_make,
        "vehicle_model": repair_order.vehicle_model,
        "contragent_name": repair_order.contragent.name if repair_order.contragent else None,
        "parts_total": len(results),
        "parts_exact": parts_by_source.get("exact_article_match", 0),
        "parts_cross_ref": parts_by_source.get("parts_supplier_cross_reference", 0),
        "parts_llm_guess": parts_by_source.get("llm_fallback", 0),
        "parts_no_match": parts_by_source.get("no_match_found", 0),
        "parts_llm_error": parts_by_source.get("llm_error", 0),
        "labor_total": len(labor_results),
        "labor_exact": labor_by_source.get("autodata_exact", 0) + labor_by_source.get("contract_catalog_exact", 0),
        "labor_llm_guess": labor_by_source.get("llm_fallback", 0) + labor_by_source.get("llm_fallback_contract_catalog", 0),
        "labor_cross_make_estimate": (
            labor_by_source.get("llm_fallback_cross_make", 0)
            + labor_by_source.get("llm_fallback_cross_make_contract_catalog", 0)
        ),
        "labor_from_repair_order_itself": labor_by_source.get("repair_order_stated_value", 0),
        "labor_no_match": labor_by_source.get("no_match_found", 0),
        "labor_llm_error": labor_by_source.get("llm_error", 0),
    }

    try:
        result = llm_client.summarize_review(stats)
    except Exception as exc:
        logger.warning("Не удалось получить AI-сводку для repair_order_id=%s: %s", repair_order.id, exc)
        return None

    summary = result.get("summary") if isinstance(result, dict) else None
    return summary.strip() if isinstance(summary, str) and summary.strip() else None


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
        # Марка самого заказ-наряда раньше нигде не нормализовалась —
        # бралась как есть из текста файла ("Автомобиль: Шевроле Лачетти")
        # и в таком виде шла и в фильтр по марке при сопоставлении
        # (matcher._contract_candidate_pool), и в поиск ставки/нормо-часов
        # ниже — там сравнение со справочником/каталогом ТОЧНОЕ, так что
        # кириллица или опечатка в самом заказ-наряде не находились, даже
        # если каталог был уже правильно затегирован. Тот же принцип
        # "ИИ проверяет и адаптирует данные перед сопоставлением", что и
        # для каталога (см. contract_catalog_import._normalize_unresolved_brands),
        # только для одной конкретной марки, а не пакета сразу.
        repair_order.vehicle_make = normalize_brand_with_ai_fallback(repair_order.vehicle_make, llm_client)
        repair_order.vehicle_model = repair_order.vehicle_model or meta.get("vehicle_model")
        repair_order.vehicle_vin = repair_order.vehicle_vin or meta.get("vehicle_vin")
        repair_order.vehicle_year = repair_order.vehicle_year or meta.get("vehicle_year")
        repair_order.order_number = repair_order.order_number or meta.get("order_number")
        repair_order.order_date = repair_order.order_date or meta.get("order_date")
        repair_order.parsed_lines = part_lines
        # Сохраняем строки как они были распознаны в файле — ДО
        # сопоставления (см. raw_import_staging.py: то же самое "сырые
        # данные, потом постоянные таблицы", что и для каталога договора
        # выше). Не в parsed_lines (то поле — только запчасти, и не
        # переживает повторный анализ), а отдельно и разом с работами.
        stage_raw_rows(part_lines, row_kind="order_part", repair_order_id=repair_order.id)
        stage_raw_rows(labor_lines_raw, row_kind="order_labor", repair_order_id=repair_order.id)
    except DocumentParseError as exc:
        message = f"Не удалось прочитать заказ-наряд: {exc}"
        repair_order.status = RepairOrderStatus.FAILED
        repair_order.error_message = message
        log_change("repair_order", repair_order.id, "failed", details={"error": message, "stage": "parsing"})
        db.session.commit()
        return {"status": "failed", "error": message}
    except Exception as exc:
        # Как и для import_contract_files ниже: непредвиденная ошибка (не
        # формат файла, а, например, сбой БД или необработанное исключение
        # ИИ-нормализации марки) не должна оставлять заказ-наряд в статусе
        # "parsing" навсегда без единого сообщения — job_queue.py ловит
        # Exception только чтобы не уронить воркер-поток, но не трогает
        # статус записи, поэтому это нужно сделать здесь.
        logger.exception("_parse_repair_order_files упал для repair_order_id=%s", repair_order_id)
        message = f"Не удалось разобрать заказ-наряд: {exc}"
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
        except Exception as exc:
            logger.exception("import_contract_files упал для contract_id=%s", contract.id)
            message = f"Не удалось разобрать договор: {exc}"
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

    supplier_client = build_configured_supplier_client(current_app.config)

    try:
        results = match_all_against_contract(
            part_lines, contract.id, supplier_client, llm_client, repair_order.vehicle_make
        )
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

    hourly_rate = resolve_hourly_rate(repair_order)
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

    # Если каталог/AutoData не смог определить норму часов операции — не
    # оставляем её пустой, когда сам заказ-наряд её уже содержит (1С-выгрузка
    # парсит колонку "Норма, ч" — см. document_parser.parse_repair_order_export).
    # Заказчик подтвердил: справочника с нормо-часами почти никогда нет
    # (98% случаев), поэтому то, что мехник реально вписал в наряд для ЭТОЙ
    # работы, надёжнее пустого поля "не указана", которое иначе пришлось бы
    # заполнять вручную по памяти — matched_operation_name остаётся пустым
    # (каталог всё равно не подтвердил), но норма часов уже не пропадает.
    for result, raw_line in zip(labor_results, labor_lines_raw):
        if result.get("norm_hours") is None:
            source_norm_hours = raw_line.get("source_norm_hours")
            if source_norm_hours is not None:
                result["norm_hours"] = source_norm_hours
                result["raw_match_data"] = {
                    "source": "repair_order_stated_value",
                    "match_attempt_source": (result.get("raw_match_data") or {}).get("source"),
                }

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

    repair_order.review_summary = _generate_review_summary(repair_order, results, labor_results, llm_client)
    mark_rows_moved(repair_order_id=repair_order.id, row_kind="order_part")
    mark_rows_moved(repair_order_id=repair_order.id, row_kind="order_labor")
    repair_order.status = RepairOrderStatus.NEEDS_REVIEW
    log_change(
        "repair_order",
        repair_order.id,
        "needs_review",
        details={"matches_created": len(results), "labor_lines_created": len(labor_results)},
    )
    db.session.commit()

    return {"status": "ok", "matches_created": len(results), "labor_lines_created": len(labor_results)}
