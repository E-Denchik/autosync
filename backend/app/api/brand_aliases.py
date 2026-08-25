"""Справочник соответствий "марка в файле поставщика -> каноничная марка,
как в заказ-наряде" (см. app/models/brand_alias.py,
services/document_parser.py::_normalize_brand_label). Заказчик пополняет
его сам — вручную или файлом — без правки кода и пересборки; для того,
что справочник ещё не знает, есть кнопка ИИ-нормализации (тот же
LLMClient.normalize_brand_labels, что автоматически срабатывает при
импорте договора — см. services/contract_catalog_import.py)."""

import os
import uuid

import pandas as pd
from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import BrandAlias
from app.services.history import log_change
from app.services.llm_client import LLMClient
from app.services.pagination import paginate, paginated_response

bp = Blueprint("brand_aliases", __name__)

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv"}


def _serialize(entry: BrandAlias) -> dict:
    return {
        "id": entry.id,
        "alias": entry.alias,
        "canonical_make": entry.canonical_make,
        "source": entry.source,
    }


@bp.get("")
def list_aliases():
    query = BrandAlias.query
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(BrandAlias.alias.ilike(like), BrandAlias.canonical_make.ilike(like)))
    only_unresolved = request.args.get("unresolved") == "1"
    if only_unresolved:
        query = query.filter(BrandAlias.canonical_make.is_(None))
    query = query.order_by(BrandAlias.alias)
    entries, total = paginate(query, request.args)
    return paginated_response([_serialize(e) for e in entries], total)


@bp.post("")
def create_alias():
    body = request.get_json(force=True) or {}
    alias = (body.get("alias") or "").strip()
    if not alias:
        return jsonify(error="'alias' обязателен"), 400
    if BrandAlias.query.filter(db.func.upper(BrandAlias.alias) == alias.upper()).first():
        return jsonify(error=f"Марка {alias!r} уже есть в справочнике"), 409

    canonical = (body.get("canonical_make") or "").strip().upper() or None
    entry = BrandAlias(alias=alias, canonical_make=canonical, source="manual")
    db.session.add(entry)
    db.session.flush()
    log_change("brand_alias", entry.id, "created")
    db.session.commit()
    return jsonify(_serialize(entry)), 201


@bp.patch("/<int:entry_id>")
def update_alias(entry_id: int):
    entry = db.get_or_404(BrandAlias, entry_id)
    body = request.get_json(force=True) or {}

    if "alias" in body:
        alias = (body.get("alias") or "").strip()
        if not alias:
            return jsonify(error="'alias' не может быть пустым"), 400
        entry.alias = alias
    if "canonical_make" in body:
        entry.canonical_make = (body.get("canonical_make") or "").strip().upper() or None
    entry.source = "manual"

    log_change("brand_alias", entry.id, "updated")
    db.session.commit()
    return jsonify(_serialize(entry))


@bp.delete("/<int:entry_id>")
def delete_alias(entry_id: int):
    entry = db.get_or_404(BrandAlias, entry_id)
    db.session.delete(entry)
    log_change("brand_alias", entry_id, "deleted")
    db.session.commit()
    return "", 204


def _read_two_columns(file_path: str) -> list[tuple[str, str | None]]:
    """Файл с маркой в первой колонке и (опционально) каноничным написанием
    во второй — под шапку не подстраиваемся (в отличие от document_parser.py,
    тут заведомо простой, специально подготовленный заказчиком файл, а не
    произвольный прайс-лист поставщика), берём первые две колонки как есть."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        df = pd.read_csv(file_path, header=0, dtype=str)
    else:
        engine = "xlrd" if ext == ".xls" else ("odf" if ext == ".ods" else "openpyxl")
        df = pd.read_excel(file_path, header=0, dtype=str, engine=engine)

    if df.shape[1] < 1:
        return []
    rows = []
    for _, row in df.iterrows():
        alias = row.iloc[0]
        if pd.isna(alias) or not str(alias).strip():
            continue
        canonical = row.iloc[1] if df.shape[1] > 1 else None
        canonical = None if canonical is None or pd.isna(canonical) or not str(canonical).strip() else str(canonical).strip()
        rows.append((str(alias).strip(), canonical))
    return rows


@bp.post("/upload")
def upload_file():
    """Файл с марками (см. _read_two_columns) — upsert по alias
    (регистронезависимо). Если для алиаса, который уже есть, канонику не
    передали — не затираем то, что там уже было (файл без второй колонки
    не должен обнулять то, что распознала ИИ/вписал человек руками)."""
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="Нужен файл 'file'"), 400

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)

    created = 0
    updated = 0
    errors = []
    for file_storage in files:
        ext = os.path.splitext(file_storage.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"{file_storage.filename}: неподдерживаемый тип файла {ext}")
            continue

        stored_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
        file_storage.save(stored_path)
        try:
            rows = _read_two_columns(stored_path)
        except Exception as exc:
            errors.append(f"{file_storage.filename}: {exc}")
            continue
        finally:
            os.remove(stored_path)

        for alias, canonical in rows:
            existing = BrandAlias.query.filter(db.func.upper(BrandAlias.alias) == alias.upper()).first()
            if existing is None:
                db.session.add(BrandAlias(alias=alias, canonical_make=canonical.upper() if canonical else None, source="upload"))
                created += 1
            elif canonical:
                existing.canonical_make = canonical.upper()
                existing.source = "upload"
                updated += 1

    if errors and created == 0 and updated == 0:
        return jsonify(error="; ".join(errors)), 400

    log_change("brand_alias_import", 0, "imported", details={"created": created, "updated": updated})
    db.session.commit()
    return jsonify({"created": created, "updated": updated, "errors": errors}), 201


@bp.post("/normalize")
def normalize_unresolved():
    """Ручной запуск того же ИИ-шага, что автоматически идёт при импорте
    договора (см. services/contract_catalog_import.py::_normalize_unresolved_brands)
    — здесь по явному нажатию, для алиасов без canonical_make (загруженных
    файлом без второй колонки, или добавленных вручную без неё)."""
    unresolved = BrandAlias.query.filter(BrandAlias.canonical_make.is_(None)).all()
    if not unresolved:
        return jsonify(normalized=0, total=0)

    llm_client = LLMClient(current_app.config["LLM_SERVICE_URL"])
    try:
        mapping = llm_client.normalize_brand_labels([e.alias for e in unresolved])
    except Exception as exc:
        return jsonify(error=f"ИИ-нормализация недоступна: {exc}"), 502

    normalized = 0
    by_alias = {e.alias: e for e in unresolved}
    for alias, canonical in mapping.items():
        if not canonical:
            continue
        entry = by_alias.get(alias)
        if entry is None:
            continue
        entry.canonical_make = canonical.strip().upper()
        entry.source = "llm"
        normalized += 1

    log_change("brand_alias", 0, "bulk_normalized_by_llm", details={"normalized": normalized, "total": len(unresolved)})
    db.session.commit()
    return jsonify(normalized=normalized, total=len(unresolved))
