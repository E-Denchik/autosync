"""Внутренняя номенклатура/склад заказчика — просмотр, ручное
редактирование и загрузка файлом (см. services/nomenclature_import.py).
Используется как локальный источник для обогащения PartMatch, пока не
подтверждён реальный API (см. services/nomenclature_client.py)."""

import os
import uuid

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app.auth import get_current_user, login_required
from app.extensions import db
from app.models import NomenclatureEntry
from app.services.history import log_change
from app.services.nomenclature_import import NomenclatureImportError, import_nomenclature_file

bp = Blueprint("nomenclature", __name__)
bp.before_request(login_required(lambda: None))

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv"}


def _serialize(entry: NomenclatureEntry) -> dict:
    return {
        "id": entry.id,
        "code": entry.code,
        "cat_number": entry.cat_number,
        "manufacturer": entry.manufacturer,
        "name": entry.name,
        "unit": entry.unit,
        "stock_qty": float(entry.stock_qty) if entry.stock_qty is not None else None,
        "ordered_qty": float(entry.ordered_qty) if entry.ordered_qty is not None else None,
        "reserved_qty": float(entry.reserved_qty) if entry.reserved_qty is not None else None,
        "in_production_qty": float(entry.in_production_qty) if entry.in_production_qty is not None else None,
        "warehouse": entry.warehouse,
        "price": float(entry.price) if entry.price is not None else None,
        "source": entry.source,
    }


@bp.get("")
def list_entries():
    query = NomenclatureEntry.query
    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                NomenclatureEntry.name.ilike(like),
                NomenclatureEntry.code.ilike(like),
                NomenclatureEntry.cat_number.ilike(like),
            )
        )
    entries = query.order_by(NomenclatureEntry.name).limit(500).all()
    return jsonify([_serialize(e) for e in entries])


@bp.post("")
def create_entry():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify(error="'name' обязателен"), 400

    entry = NomenclatureEntry(
        name=name,
        code=(body.get("code") or "").strip() or None,
        cat_number=(body.get("cat_number") or "").strip() or None,
        manufacturer=(body.get("manufacturer") or "").strip() or None,
        unit=(body.get("unit") or "").strip() or None,
        warehouse=(body.get("warehouse") or "").strip() or None,
        stock_qty=body.get("stock_qty"),
        ordered_qty=body.get("ordered_qty"),
        reserved_qty=body.get("reserved_qty"),
        in_production_qty=body.get("in_production_qty"),
        price=body.get("price"),
        source="manual",
    )
    db.session.add(entry)
    db.session.flush()
    log_change("nomenclature_entry", entry.id, "created", actor=get_current_user())
    db.session.commit()
    return jsonify(_serialize(entry)), 201


@bp.patch("/<int:entry_id>")
def update_entry(entry_id: int):
    entry = db.get_or_404(NomenclatureEntry, entry_id)
    body = request.get_json(force=True) or {}

    str_fields = ["code", "cat_number", "manufacturer", "name", "unit", "warehouse"]
    num_fields = ["stock_qty", "ordered_qty", "reserved_qty", "in_production_qty", "price"]
    for field in str_fields:
        if field in body:
            setattr(entry, field, (body.get(field) or "").strip() or None)
    for field in num_fields:
        if field in body:
            setattr(entry, field, body.get(field))

    log_change("nomenclature_entry", entry.id, "updated", actor=get_current_user())
    db.session.commit()
    return jsonify(_serialize(entry))


@bp.delete("/<int:entry_id>")
def delete_entry(entry_id: int):
    entry = db.get_or_404(NomenclatureEntry, entry_id)
    db.session.delete(entry)
    log_change("nomenclature_entry", entry_id, "deleted", actor=get_current_user())
    db.session.commit()
    return "", 204


@bp.post("/upload")
def upload_file():
    """Загружает выгрузку номенклатуры файлом и upsert-ит записи (см.
    nomenclature_import.py) — синхронно: типичная выгрузка склада разбирается
    за доли секунды через pandas, отдельная очередь не нужна."""
    if "file" not in request.files:
        return jsonify(error="Нужен файл 'file'"), 400

    file_storage = request.files["file"]
    filename = secure_filename(file_storage.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify(error=f"Неподдерживаемый тип файла: {ext}"), 400

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    stored_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
    file_storage.save(stored_path)

    try:
        summary = import_nomenclature_file(stored_path)
    except NomenclatureImportError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        os.remove(stored_path)

    log_change(
        "nomenclature_import",
        0,
        "imported",
        actor=get_current_user(),
        details={"filename": filename, **summary},
    )
    db.session.commit()
    return jsonify(summary), 201
