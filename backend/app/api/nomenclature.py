"""Внутренняя номенклатура/склад заказчика — просмотр, ручное
редактирование и загрузка файлом (см. services/nomenclature_import.py).
Используется как локальный источник для обогащения PartMatch, пока не
подтверждён реальный API (см. services/nomenclature_client.py)."""

import os
import uuid

import openpyxl
from flask import Blueprint, current_app, jsonify, request, send_file
from openpyxl.styles import Font

from app.extensions import db
from app.models import NomenclatureEntry
from app.services.history import log_change
from app.services.llm_client import LLMClient
from app.services.nomenclature_import import NomenclatureImportError, import_nomenclature_file
from app.services.ocr import IMAGE_EXTENSIONS
from app.services.pagination import paginate, paginated_response

bp = Blueprint("nomenclature", __name__)

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"} | IMAGE_EXTENSIONS


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
    query = query.order_by(NomenclatureEntry.name)
    entries, total = paginate(query, request.args)
    return paginated_response([_serialize(e) for e in entries], total)


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
    log_change("nomenclature_entry", entry.id, "created")
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

    log_change("nomenclature_entry", entry.id, "updated")
    db.session.commit()
    return jsonify(_serialize(entry))


@bp.delete("/<int:entry_id>")
def delete_entry(entry_id: int):
    entry = db.get_or_404(NomenclatureEntry, entry_id)
    db.session.delete(entry)
    log_change("nomenclature_entry", entry_id, "deleted")
    db.session.commit()
    return "", 204


@bp.get("/template")
def download_template():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Номенклатура"
    headers = [
        "Код",
        "№ кат.",
        "Производитель",
        "Наименование",
        "Единица",
        "Остаток",
        "Заказано",
        "В резерве",
        "В производстве",
        "Склад",
        "Цена",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.append(["PN-1001", "CAT-55", "LUZAR", "Насос водяной", "шт", 10, 0, 2, 0, "Основной", 3860])
    for col, width in zip("ABCDEFGHIJK", [12, 12, 16, 32, 10, 10, 10, 10, 14, 14, 10]):
        ws.column_dimensions[col].width = width

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    output_path = os.path.join(upload_dir, f"nomenclature-template-{uuid.uuid4().hex}.xlsx")
    wb.save(output_path)
    return send_file(output_path, as_attachment=True, download_name="autosync-shablon-nomenklatura.xlsx")


@bp.post("/upload")
def upload_file():
    """Загружает одну или несколько выгрузок номенклатуры файлом и
    upsert-ит записи (см. nomenclature_import.py) — синхронно: типичная
    выгрузка склада разбирается за доли секунды через pandas, отдельная
    очередь не нужна."""
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="Нужен файл 'file'"), 400

    totals = {"rows_parsed": 0, "created": 0, "updated": 0}
    errors = []
    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    llm_client = LLMClient(current_app.config["LLM_SERVICE_URL"])

    for file_storage in files:
        ext = os.path.splitext(file_storage.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"{file_storage.filename}: неподдерживаемый тип файла {ext}")
            continue

        stored_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
        file_storage.save(stored_path)
        try:
            summary = import_nomenclature_file(stored_path, llm_client)
            for key in totals:
                totals[key] += summary[key]
            log_change(
                "nomenclature_import",
                0,
                "imported",
                details={"filename": file_storage.filename, **summary},
            )
        except NomenclatureImportError as exc:
            errors.append(f"{file_storage.filename}: {exc}")
        finally:
            os.remove(stored_path)

    if errors and totals["rows_parsed"] == 0:
        return jsonify(error="; ".join(errors)), 400

    db.session.commit()
    return jsonify({**totals, "errors": errors}), 201
