from flask import Blueprint, jsonify, request

from app.services import company_profile

bp = Blueprint("company_profile", __name__)


@bp.get("")
def get_profile():
    return jsonify(company_profile.load())


@bp.put("")
def update_profile():
    body = request.get_json(force=True) or {}
    company_profile.save(body)
    return jsonify(company_profile.load())
