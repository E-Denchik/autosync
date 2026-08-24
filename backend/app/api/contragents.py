import os

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import Contragent, ContragentHourlyRate
from app.services.document_parser import DocumentParseError
from app.services.hourly_rate_import import import_hourly_rates
from app.services.upload_helpers import save_upload

bp = Blueprint("contragents", __name__)

RATE_TABLE_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv"}


def _serialize(c: Contragent) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "hourly_rate": float(c.hourly_rate),
        "notes": c.notes,
    }


@bp.get("")
def list_contragents():
    contragents = Contragent.query.order_by(Contragent.name).all()
    return jsonify([_serialize(c) for c in contragents])


@bp.post("")
def create_contragent():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify(error="'name' обязателен"), 400
    try:
        hourly_rate = float(body.get("hourly_rate"))
    except (TypeError, ValueError):
        return jsonify(error="'hourly_rate' должен быть числом"), 400
    if hourly_rate < 0:
        return jsonify(error="'hourly_rate' не может быть отрицательной"), 400

    if Contragent.query.filter_by(name=name).first():
        return jsonify(error=f"Контрагент «{name}» уже существует"), 409

    contragent = Contragent(name=name, hourly_rate=hourly_rate, notes=body.get("notes"))
    db.session.add(contragent)
    db.session.commit()
    return jsonify(_serialize(contragent)), 201


@bp.patch("/<int:contragent_id>")
def update_contragent(contragent_id: int):
    contragent = db.get_or_404(Contragent, contragent_id)
    body = request.get_json(force=True) or {}

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            return jsonify(error="'name' не может быть пустым"), 400
        contragent.name = name
    if "hourly_rate" in body:
        try:
            contragent.hourly_rate = float(body.get("hourly_rate"))
        except (TypeError, ValueError):
            return jsonify(error="'hourly_rate' должен быть числом"), 400
    if "notes" in body:
        contragent.notes = body.get("notes")

    db.session.commit()
    return jsonify(_serialize(contragent))


@bp.delete("/<int:contragent_id>")
def delete_contragent(contragent_id: int):
    contragent = db.get_or_404(Contragent, contragent_id)
    db.session.delete(contragent)
    db.session.commit()
    return "", 204


@bp.get("/<int:contragent_id>/hourly-rates")
def list_hourly_rates(contragent_id: int):
    db.get_or_404(Contragent, contragent_id)
    rates = (
        ContragentHourlyRate.query.filter_by(contragent_id=contragent_id)
        .order_by(ContragentHourlyRate.vehicle_make)
        .all()
    )
    return jsonify(
        [{"id": r.id, "vehicle_make": r.vehicle_make, "hourly_rate": float(r.hourly_rate)} for r in rates]
    )


@bp.post("/<int:contragent_id>/hourly-rates")
def create_hourly_rate(contragent_id: int):
    db.get_or_404(Contragent, contragent_id)
    body = request.get_json(force=True) or {}
    vehicle_make = (body.get("vehicle_make") or "").strip()
    if not vehicle_make:
        return jsonify(error="'vehicle_make' обязателен"), 400
    try:
        hourly_rate = float(body.get("hourly_rate"))
    except (TypeError, ValueError):
        return jsonify(error="'hourly_rate' должен быть числом"), 400
    if hourly_rate <= 0:
        return jsonify(error="'hourly_rate' должен быть положительным"), 400

    rate = ContragentHourlyRate(contragent_id=contragent_id, vehicle_make=vehicle_make, hourly_rate=hourly_rate)
    db.session.add(rate)
    db.session.commit()
    return jsonify({"id": rate.id, "vehicle_make": rate.vehicle_make, "hourly_rate": float(rate.hourly_rate)}), 201


@bp.delete("/<int:contragent_id>/hourly-rates/<int:rate_id>")
def delete_hourly_rate(contragent_id: int, rate_id: int):
    rate = ContragentHourlyRate.query.filter_by(id=rate_id, contragent_id=contragent_id).first_or_404()
    db.session.delete(rate)
    db.session.commit()
    return "", 204


@bp.post("/<int:contragent_id>/hourly-rates/import")
def import_hourly_rates_file(contragent_id: int):
    """Массовая загрузка ставок по маркам ТС файлом — вместо добавления
    по одной через форму выше. Формат файла заранее не диктуется: колонки
    "марка"/"ставка" ищутся по синонимам в заголовке (см.
    document_parser.parse_hourly_rate_table), а не по жёсткому шаблону."""
    db.get_or_404(Contragent, contragent_id)
    file = request.files.get("file")
    if not file:
        return jsonify(error="Нужен файл 'file'"), 400

    try:
        path = save_upload(file, RATE_TABLE_EXTENSIONS)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    try:
        result = import_hourly_rates(ContragentHourlyRate, "contragent_id", contragent_id, path)
    except DocumentParseError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        if os.path.isfile(path):
            os.remove(path)

    return jsonify(result), 200
