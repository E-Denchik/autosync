"""Сводная статистика для лендинга фронта — избавляет фронт от нескольких
запросов подряд ради счётчиков на главном экране."""

from flask import Blueprint, jsonify

from app.auth import login_required
from app.models import (
    PartMatch,
    PriceSnapshot,
    PriceSuggestionStatus,
    Product,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)

bp = Blueprint("dashboard", __name__)
bp.before_request(login_required(lambda: None))


@bp.get("/summary")
def summary():
    return jsonify(
        products_total=Product.query.count(),
        pending_price_suggestions=PriceSnapshot.query.filter_by(
            status=PriceSuggestionStatus.PENDING
        ).count(),
        repair_orders_total=RepairOrder.query.count(),
        repair_orders_needs_review=RepairOrder.query.filter_by(
            status=RepairOrderStatus.NEEDS_REVIEW
        ).count(),
        pending_part_matches=PartMatch.query.filter_by(review_status=ReviewStatus.PENDING).count(),
    )
