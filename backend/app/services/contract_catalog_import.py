from __future__ import annotations

import logging
import os

from app.extensions import db
from app.models import (
    BrandAlias,
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
    parse_price_catalog_single_sheet_sections,
    parse_repair_order_export,
)
from app.services.history import log_change
from app.services.matcher import normalize_article
from app.services.progress_tracker import tracking as track_progress
from app.services.raw_import_staging import mark_rows_moved, stage_raw_rows

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
    existing_by_article = {
        p.article: (p.id, p.vehicle_make)
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
        existing_id, existing_make = existing_by_article.get(article, (None, None))
        # Не затираем уже проставленную марку, если ЭТА строка её не знает
        # (например, повторный импорт через формат "экспорт заказ-наряда",
        # который бренд не определяет) — иначе разметка по марке из
        # первого, брендового импорта терялась бы при любом последующем.
        vehicle_make = line.get("vehicle_make") if line.get("vehicle_make") is not None else existing_make
        row = {
            "contract_id": contract_id,
            "article": article,
            "article_normalized": normalize_article(article),
            "name": line.get("name"),
            "qty": line.get("qty"),
            "price": line.get("price"),
            "vehicle_make": vehicle_make,
        }
        if article and existing_id is not None:
            to_update.append({**row, "id": existing_id})
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


def _labor_norm_key(operation_name: str | None, vehicle_make: str | None, vehicle_model: str | None) -> tuple:
    # Тот же регистронезависимый ключ, что и в labor_matcher._contract_labor_candidates/
    # match_labor_line_against_contract — иначе дедупликация здесь и сопоставление
    # там расходились бы в том, что считать "той же" нормой.
    return (
        (operation_name or "").strip().lower(),
        (vehicle_make or "").strip().lower(),
        (vehicle_model or "").strip().lower(),
    )


def _bulk_insert_labor_norms(
    contract_id: int, lines: list[dict], vehicle_make: str | None, vehicle_model: str | None
) -> dict:
    """Пишет строки норм-часов как ContractLaborNorm. Норма с тем же
    (операция, марка, модель) в этом договоре ОБНОВЛЯЕТСЯ (норма-часы), а не
    создаётся заново — иначе повторная загрузка файла норм через "Добавить ещё
    файлы" (см. app/api/contracts.py::import_more_files) удваивала бы список
    норм при каждой загрузке, как и было раньше исправлено для ContractPart
    в _bulk_insert_parts."""
    existing_by_key = {
        _labor_norm_key(r.operation_name, r.vehicle_make, r.vehicle_model): r.id
        for r in ContractLaborNorm.query.filter_by(contract_id=contract_id).all()
    }

    to_insert: list[dict] = []
    to_update: list[dict] = []
    seen_in_batch: dict[tuple, int] = {}
    for line in lines:
        if not line.get("description") or line.get("norm_hours") is None:
            continue
        key = _labor_norm_key(line.get("description"), vehicle_make, vehicle_model)
        row = {
            "contract_id": contract_id,
            "operation_name": line.get("description"),
            "vehicle_make": vehicle_make,
            "vehicle_model": vehicle_model,
            "norm_hours": line.get("norm_hours"),
        }
        existing_id = existing_by_key.get(key)
        if existing_id is not None:
            to_update.append({**row, "id": existing_id})
        elif key in seen_in_batch:
            # Та же операция несколько раз в одном файле — оставляем последнюю строку.
            to_insert[seen_in_batch[key]] = row
        else:
            seen_in_batch[key] = len(to_insert)
            to_insert.append(row)

    for i in range(0, len(to_insert), BATCH_SIZE):
        db.session.bulk_insert_mappings(ContractLaborNorm, to_insert[i : i + BATCH_SIZE])
    for i in range(0, len(to_update), BATCH_SIZE):
        db.session.bulk_update_mappings(ContractLaborNorm, to_update[i : i + BATCH_SIZE])

    return {"created": len(to_insert), "updated": len(to_update)}


def _parse_one_contract_file(path: str, llm_client) -> dict:
    """Разбирает ОДИН файл каталога договора и ничего не пишет в БД (кроме
    единственного read-only запроса к BrandAlias внутри
    parse_price_catalog_by_brand/_normalize_brand_label — как и в
    matcher.py: _contract_candidate_pool, это безопасно параллелить).
    Запись остаётся строго последовательной в вызывающем потоке (см.
    import_contract_files) — дедуп по артикулу в _bulk_insert_parts делает
    SELECT по contract_id и должен видеть уже вставленные (пусть и не
    закоммиченные — автофлаш той же сессии) строки ПРЕДЫДУЩИХ файлов,
    иначе два файла с одним и тем же новым артикулом создали бы дубль.

    Никогда не бросает исключение — плохой формат ОДНОГО файла среди
    десятков/сотен не должен обрывать разбор всех остальных (раньше
    ровно так и было: DocumentParseError из этой функции улетала до
    import_contract_job, ничего из уже разобранного не коммитилось, и
    вся загрузка целиком проваливалась из-за одного файла)."""
    filename = os.path.basename(path)
    try:
        export = parse_repair_order_export(path)
        if export is not None:
            return {"filename": filename, "kind": "export", "export": export, "error": None}

        # Всегда разбираем ВСЕ найденные листы марок разом (vehicle_make=None
        # заставляет parse_price_catalog_by_brand взять все листы — см. её
        # докстринг), а не только текущую марку заказ-наряда: договор/прайс
        # загружается один раз и потом переиспользуется для заказ-нарядов
        # разных марок (см. contract.status == PARSED в
        # repair_order_processor.py — повторно этот код для того же
        # договора уже не выполнится). Раньше при первом использовании
        # договора для, скажем, Hyundai в БД попадал только лист Hyundai, и
        # заказ-наряд по другой марке из того же файла (например, ВАЗ/Lada)
        # оставался вообще без единой запчасти для сопоставления.
        lines = parse_price_catalog_by_brand(path, None)
        if lines is None:
            # Тот же смысл, что и выше, но раздел на марку — не отдельный
            # лист, а строка-маркер внутри одного листа (см. её докстринг —
            # реальный файл заказчика на 25000+ строк одним листом).
            lines = parse_price_catalog_single_sheet_sections(path)
        if lines is None:
            lines = parse_document_with_ocr_fallback(path, llm_client, DOCUMENT_LINE_FIELDS)
        return {"filename": filename, "kind": "catalog", "lines": lines, "error": None}
    except DocumentParseError as exc:
        return {"filename": filename, "kind": None, "error": str(exc)}
    except Exception as exc:
        logger.exception("Не удалось разобрать файл %s при импорте каталога договора", filename)
        return {"filename": filename, "kind": None, "error": str(exc)}


def import_contract_files(contract_id: int, paths: list[str], vehicle_make: str | None, llm_client) -> dict:
    """179 файлов договора раньше разбирались строго по одному — каждый
    файл без готовой табличной структуры уходил в OCR/LLM-fallback
    (parse_document_with_ocr_fallback), а на слабой машине/большой модели
    один такой вызов мог занимать минуту и больше; сотня файлов
    превращалась в часы ожидания без единого признака прогресса. Сам
    разбор файла — чистая функция без записи в БД (см.
    _parse_one_contract_file), поэтому его можно раздать по пулу потоков
    точно так же, как уже разбираются строки одного заказ-наряда в
    matcher.py/labor_matcher.py — см. app/services/parallel.py про то, что
    это НЕ параллель разных моделей, а несколько запросов к ОДНОЙ уже
    загруженной. Число одновременных запросов адаптируется под память/CPU
    этого компьютера (llm_workers() -> performance_settings.py), поэтому
    для владельца слабой машины пул сам сузится, а не просто станет "быстрее
    для всех и упадёт по OOM у него"."""
    from app.services.parallel import llm_workers, map_with_app_context

    parsed_results = map_with_app_context(
        lambda path: _parse_one_contract_file(path, llm_client),
        paths,
        max_workers=llm_workers(),
    )

    parts_created = 0
    parts_updated = 0
    labor_norms_created = 0
    labor_norms_updated = 0
    failed_files: list[dict] = []

    # Запись в БД — строго последовательно и в исходном порядке файлов
    # (map_with_app_context сохраняет порядок items), ради того же дедупа
    # по артикулу, что и раньше в обычном цикле.
    for parsed in parsed_results:
        filename = parsed["filename"]
        if parsed["error"] is not None:
            failed_files.append({"filename": filename, "error": parsed["error"]})
            continue

        if parsed["kind"] == "export":
            export = parsed["export"]
            # Сохраняем строки как они были распознаны в файле — ДО того,
            # как они станут ContractPart (см. raw_import_staging.py — тот
            # же принцип "сначала сырые данные, потом постоянные таблицы"
            # для каталога договора, что и для заказ-наряда ниже).
            stage_raw_rows(export["part_lines"], row_kind="catalog_part", contract_id=contract_id, source_filename=filename)
            parts_result = _bulk_insert_parts(contract_id, export["part_lines"])
            parts_created += parts_result["created"]
            parts_updated += parts_result["updated"]
            labor_norms_result = _bulk_insert_labor_norms(
                contract_id,
                export["labor_lines"],
                export["meta"].get("vehicle_make") or vehicle_make,
                export["meta"].get("vehicle_model"),
            )
            labor_norms_created += labor_norms_result["created"]
            labor_norms_updated += labor_norms_result["updated"]
            continue

        lines = parsed["lines"]
        stage_raw_rows(lines, row_kind="catalog_part", contract_id=contract_id, source_filename=filename)
        parts_result = _bulk_insert_parts(contract_id, lines)
        parts_created += parts_result["created"]
        parts_updated += parts_result["updated"]

    # "ИИ проверяет и адаптирует сохранённые данные" — уже застейджены
    # выше, дальше сама марка/каталог доводятся до нашего стандарта.
    brands_normalized = _normalize_unresolved_brands(contract_id, llm_client)
    mark_rows_moved(contract_id=contract_id, row_kind="catalog_part")

    db.session.commit()
    return {
        "parts_created": parts_created,
        "parts_updated": parts_updated,
        "labor_norms_created": labor_norms_created,
        "labor_norms_updated": labor_norms_updated,
        "brands_normalized": brands_normalized,
        "failed_files": failed_files,
    }


def _normalize_unresolved_brands(contract_id: int, llm_client) -> int:
    """Марки, которых нет в справочнике BrandAlias (см. document_parser.
    _normalize_brand_label — при отсутствии совпадения строки остаются с
    исходным, необработанным написанием) — заказчик попросил: сохранённые
    данные проверяет и адаптирует под наш стандарт выбранная им ИИ, а уже
    ПОТОМ идёт сопоставление (см. repair_order_processor.process_upload_job:
    вызывается после этой функции). Как и весь остальной код с LLM в этом
    проекте — best-effort: недоступность LLM просто оставляет марку как
    есть, сопоставление всё равно продолжится (см. matcher.py/
    labor_matcher.py — тот же принцип везде)."""
    known_canonical = {
        row[0] for row in db.session.query(BrandAlias.canonical_make).filter(BrandAlias.canonical_make.isnot(None))
    }
    contract_makes = {
        row[0]
        for row in db.session.query(ContractPart.vehicle_make).filter(
            ContractPart.contract_id == contract_id, ContractPart.vehicle_make.isnot(None)
        )
    }
    unresolved = sorted(contract_makes - known_canonical)
    if not unresolved or llm_client is None:
        return 0

    try:
        mapping = llm_client.normalize_brand_labels(unresolved)
    except Exception as exc:
        logger.warning("ИИ-нормализация марок недоступна для contract_id=%s: %s", contract_id, exc)
        return 0

    normalized_count = 0
    for label, canonical in mapping.items():
        if not canonical:
            continue
        canonical = canonical.strip().upper()
        if not canonical:
            continue
        existing = BrandAlias.query.filter(db.func.upper(BrandAlias.alias) == label.upper()).first()
        if existing is None:
            db.session.add(BrandAlias(alias=label, canonical_make=canonical, source="llm"))
        elif existing.canonical_make is None:
            existing.canonical_make = canonical
            existing.source = "llm"
        else:
            continue
        ContractPart.query.filter(
            ContractPart.contract_id == contract_id, ContractPart.vehicle_make == label
        ).update({"vehicle_make": canonical}, synchronize_session=False)
        normalized_count += 1

    if normalized_count:
        log_change(
            "contract",
            contract_id,
            "brands_normalized_by_llm",
            details={"mapping": {k: v for k, v in mapping.items() if v}},
        )
    return normalized_count


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
        # Ключ прогресса — строка "contract:{id}", отдельное пространство
        # от repair_order_id внутри того же progress_tracker (см. его
        # докстринг) — /contracts/<id>/status отдаёт его фронту так же, как
        # upload.py уже делает для заказ-нарядов.
        with track_progress(f"contract:{contract_id}"):
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

    failed_files = result.get("failed_files") or []
    if failed_files and len(failed_files) == len(paths):
        # Ни один файл не разобрался — это фактический провал всей
        # загрузки (частичный успех здесь невозможен), а не "6 хороших из
        # 179" — оставляем FAILED, как и раньше для единственной ошибки.
        summary = "; ".join(f"{f['filename']} — {f['error']}" for f in failed_files[:5])
        if len(failed_files) > 5:
            summary += f" и ещё {len(failed_files) - 5}"
        contract.status = DocumentProcessingStatus.FAILED
        contract.error_message = f"Не удалось разобрать ни один файл: {summary}"
        log_change("contract", contract.id, "import_failed", details={"failed_files": failed_files})
        db.session.commit()
        return {"status": "failed", "error": contract.error_message}

    contract.status = DocumentProcessingStatus.PARSED
    contract.error_message = (
        f"{len(failed_files)} из {len(paths)} файлов не удалось разобрать — остальные загружены, "
        "подробности в истории изменений."
        if failed_files
        else None
    )
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
