from flask import Blueprint, jsonify, request

from app.auth import admin_required, login_required
from app.services import company_profile

bp = Blueprint("company_profile", __name__)
bp.before_request(login_required(lambda: None))


@bp.get("")
def get_profile():
    return jsonify(company_profile.load())


@bp.put("")
@admin_required
def update_profile():
    body = request.get_json(force=True) or {}
    company_profile.save(body)
    return jsonify(company_profile.load())
