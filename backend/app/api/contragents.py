from flask import Blueprint, jsonify, request

from app.auth import login_required
from app.extensions import db
from app.models import Contragent

bp = Blueprint("contragents", __name__)
bp.before_request(login_required(lambda: None))


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
