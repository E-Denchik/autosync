"""Сводная статистика для лендинга фронта — избавляет фронт от нескольких
запросов подряд ради счётчиков и ленты активности на главном экране."""

from flask import Blueprint, jsonify

from app.auth import login_required
from app.models import (
    LaborLine,
    PartMatch,
    PriceSnapshot,
    PriceSuggestionStatus,
    Product,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)
from app.services import llm_settings

bp = Blueprint("dashboard", __name__)
bp.before_request(login_required(lambda: None))


def _serialize_recent_order(order: RepairOrder) -> dict:
    parts_total = PartMatch.query.filter_by(repair_order_id=order.id).count()
    parts_pending = PartMatch.query.filter_by(repair_order_id=order.id, review_status=ReviewStatus.PENDING).count()
    labor_total = LaborLine.query.filter_by(repair_order_id=order.id).count()
    labor_pending = LaborLine.query.filter_by(repair_order_id=order.id, review_status=ReviewStatus.PENDING).count()
    return {
        "id": order.id,
        "original_filename": order.original_filename,
        "status": order.status.value,
        "matches_total": parts_total,
        "matches_pending": parts_pending,
        "labor_total": labor_total,
        "labor_pending": labor_pending,
        "created_at": order.created_at.isoformat(),
    }


def _serialize_recent_snapshot(snapshot: PriceSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "product_name": snapshot.product.name if snapshot.product else None,
        "product_sku": snapshot.product.sku if snapshot.product else None,
        "own_price": float(snapshot.own_price) if snapshot.own_price is not None else None,
        "suggested_price": float(snapshot.suggested_price) if snapshot.suggested_price is not None else None,
        "created_at": snapshot.created_at.isoformat(),
    }


@bp.get("/summary")
def summary():
    recent_orders = RepairOrder.query.order_by(RepairOrder.created_at.desc()).limit(5).all()
    recent_snapshots = (
        PriceSnapshot.query.filter_by(status=PriceSuggestionStatus.PENDING)
        .order_by(PriceSnapshot.created_at.desc())
        .limit(5)
        .all()
    )
    selection = llm_settings.get_selection()

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
        pending_labor_lines=LaborLine.query.filter_by(review_status=ReviewStatus.PENDING).count(),
        recent_repair_orders=[_serialize_recent_order(o) for o in recent_orders],
        recent_price_suggestions=[_serialize_recent_snapshot(s) for s in recent_snapshots],
        llm_model={"provider": selection.provider, "model": selection.model_name} if selection else None,
    )
