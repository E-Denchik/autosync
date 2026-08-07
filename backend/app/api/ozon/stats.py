from flask import Blueprint, jsonify
from sqlalchemy import func

from app.auth import login_required
from app.extensions import db
from app.models import PriceSnapshot

bp = Blueprint("ozon_stats", __name__)
bp.before_request(login_required(lambda: None))


@bp.get("/summary")
def summary():
    latest_ids_subq = (
        db.session.query(
            PriceSnapshot.product_id,
            func.max(PriceSnapshot.id).label("max_id"),
        )
        .group_by(PriceSnapshot.product_id)
        .subquery()
    )
    latest_snapshots = (
        db.session.query(PriceSnapshot)
        .join(latest_ids_subq, PriceSnapshot.id == latest_ids_subq.c.max_id)
        .all()
    )

    below_min = 0
    between = 0
    above_avg = 0
    no_data = 0
    for s in latest_snapshots:
        if s.own_price is None or (s.competitor_min_price is None and s.competitor_avg_price is None):
            no_data += 1
        elif s.competitor_min_price is not None and s.own_price < s.competitor_min_price:
            below_min += 1
        elif s.competitor_avg_price is not None and s.own_price > s.competitor_avg_price:
            above_avg += 1
        else:
            between += 1

    history_rows = (
        db.session.query(
            func.date(PriceSnapshot.created_at).label("day"),
            func.avg(PriceSnapshot.own_price).label("avg_own"),
            func.avg(PriceSnapshot.competitor_min_price).label("avg_competitor_min"),
            func.avg(PriceSnapshot.competitor_avg_price).label("avg_competitor_avg"),
        )
        .group_by(func.date(PriceSnapshot.created_at))
        .order_by(func.date(PriceSnapshot.created_at))
        .all()
    )

    return jsonify(
        products_tracked=len(latest_snapshots),
        price_position={
            "below_competitor_min": below_min,
            "between_min_and_avg": between,
            "above_competitor_avg": above_avg,
            "no_competitor_data": no_data,
        },
        price_history=[
            {
                "date": str(row.day),
                "own_price": float(row.avg_own) if row.avg_own is not None else None,
                "competitor_min_price": float(row.avg_competitor_min) if row.avg_competitor_min is not None else None,
                "competitor_avg_price": float(row.avg_competitor_avg) if row.avg_competitor_avg is not None else None,
            }
            for row in history_rows
        ],
    )


@bp.get("/products/<int:product_id>/history")
def product_history(product_id: int):
    snapshots = PriceSnapshot.query.filter_by(product_id=product_id).order_by(PriceSnapshot.created_at).all()
    return jsonify(
        [
            {
                "date": s.created_at.isoformat(),
                "own_price": float(s.own_price) if s.own_price is not None else None,
                "competitor_min_price": float(s.competitor_min_price) if s.competitor_min_price is not None else None,
                "competitor_avg_price": float(s.competitor_avg_price) if s.competitor_avg_price is not None else None,
                "suggested_price": float(s.suggested_price) if s.suggested_price is not None else None,
            }
            for s in snapshots
        ]
    )
