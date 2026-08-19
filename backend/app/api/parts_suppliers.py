from flask import Blueprint, current_app, jsonify, request

from app.services.supplier_search import search_all_suppliers

bp = Blueprint("parts_suppliers", __name__)


@bp.get("/search")
def search():
    article = (request.args.get("article") or "").strip()
    if not article:
        return jsonify(error="'article' обязателен"), 400
    brand = (request.args.get("brand") or "").strip() or None

    result = search_all_suppliers(current_app.config, article, brand=brand)
    return jsonify(result)
