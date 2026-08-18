from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import LaborCatalogEntry

bp = Blueprint("labor_catalog", __name__)


def _serialize(entry: LaborCatalogEntry) -> dict:
    return {
        "id": entry.id,
        "vehicle_make": entry.vehicle_make,
        "vehicle_model": entry.vehicle_model,
        "operation_name": entry.operation_name,
        "norm_hours": float(entry.norm_hours),
        "source": entry.source,
    }


@bp.get("")
def list_entries():
    entries = LaborCatalogEntry.query.order_by(
        LaborCatalogEntry.vehicle_make, LaborCatalogEntry.vehicle_model, LaborCatalogEntry.operation_name
    ).all()
    return jsonify([_serialize(e) for e in entries])


@bp.post("")
def create_entry():
    body = request.get_json(force=True) or {}
    vehicle_make = (body.get("vehicle_make") or "").strip()
    operation_name = (body.get("operation_name") or "").strip()
    if not vehicle_make or not operation_name:
        return jsonify(error="'vehicle_make' и 'operation_name' обязательны"), 400
    try:
        norm_hours = float(body.get("norm_hours"))
    except (TypeError, ValueError):
        return jsonify(error="'norm_hours' должен быть числом"), 400
    if norm_hours <= 0:
        return jsonify(error="'norm_hours' должен быть положительным"), 400

    entry = LaborCatalogEntry(
        vehicle_make=vehicle_make,
        vehicle_model=(body.get("vehicle_model") or "").strip() or None,
        operation_name=operation_name,
        norm_hours=norm_hours,
        source="manual",
    )
    db.session.add(entry)
    db.session.commit()
    return jsonify(_serialize(entry)), 201


@bp.patch("/<int:entry_id>")
def update_entry(entry_id: int):
    entry = db.get_or_404(LaborCatalogEntry, entry_id)
    body = request.get_json(force=True) or {}

    if "vehicle_make" in body:
        entry.vehicle_make = (body.get("vehicle_make") or "").strip()
    if "vehicle_model" in body:
        entry.vehicle_model = (body.get("vehicle_model") or "").strip() or None
    if "operation_name" in body:
        entry.operation_name = (body.get("operation_name") or "").strip()
    if "norm_hours" in body:
        try:
            entry.norm_hours = float(body.get("norm_hours"))
        except (TypeError, ValueError):
            return jsonify(error="'norm_hours' должен быть числом"), 400

    db.session.commit()
    return jsonify(_serialize(entry))


@bp.delete("/<int:entry_id>")
def delete_entry(entry_id: int):
    entry = db.get_or_404(LaborCatalogEntry, entry_id)
    db.session.delete(entry)
    db.session.commit()
    return "", 204
