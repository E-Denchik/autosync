from flask import Blueprint, jsonify, request
from sqlalchemy import func

from app.extensions import db
from app.models import PriceSnapshot, Product

bp = Blueprint("ozon_stats", __name__)

PRODUCT_SORT_FIELDS = {
    "name",
    "current_price",
    "units_sold_7d",
    "revenue_7d",
    "competitor_min_price",
    "competitor_avg_price",
}


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


@bp.get("/products")
def products():
    """Цена на Ozon рядом с продажами/выручкой за 7 дней и рыночной позицией
    по каждому товару, чтобы сравнить цену со статистикой продаж в одной таблице.
    Каталог у продавца небольшой, поэтому сортировка и позиционирование
    считаются в Python, без пагинации."""
    latest_ids_subq = (
        db.session.query(
            PriceSnapshot.product_id,
            func.max(PriceSnapshot.id).label("max_id"),
        )
        .group_by(PriceSnapshot.product_id)
        .subquery()
    )
    latest_by_product = {
        s.product_id: s
        for s in db.session.query(PriceSnapshot)
        .join(latest_ids_subq, PriceSnapshot.id == latest_ids_subq.c.max_id)
        .all()
    }

    rows = []
    for p in Product.query.all():
        snap = latest_by_product.get(p.id)
        current_price = float(p.current_price) if p.current_price is not None else None
        competitor_min = (
            float(snap.competitor_min_price) if snap and snap.competitor_min_price is not None else None
        )
        competitor_avg = (
            float(snap.competitor_avg_price) if snap and snap.competitor_avg_price is not None else None
        )

        if current_price is None or (competitor_min is None and competitor_avg is None):
            position = "no_data"
        elif competitor_min is not None and current_price < competitor_min:
            position = "below_min"
        elif competitor_avg is not None and current_price > competitor_avg:
            position = "above_avg"
        else:
            position = "between"

        rows.append(
            {
                "id": p.id,
                "sku": p.sku,
                "name": p.name,
                "category": p.category,
                "current_price": current_price,
                "units_sold_7d": p.units_sold_7d,
                "revenue_7d": float(p.revenue_7d) if p.revenue_7d is not None else None,
                "competitor_min_price": competitor_min,
                "competitor_avg_price": competitor_avg,
                "suggested_price": float(snap.suggested_price) if snap and snap.suggested_price is not None else None,
                "price_position": position,
                "snapshot_date": snap.created_at.isoformat() if snap else None,
            }
        )

    sort = request.args.get("sort")
    if sort not in PRODUCT_SORT_FIELDS:
        sort = "current_price"
    order = request.args.get("order")
    reverse = order != "asc"

    non_null = [r for r in rows if r[sort] is not None]
    null_rows = [r for r in rows if r[sort] is None]
    non_null.sort(key=lambda r: r[sort], reverse=reverse)

    return jsonify(non_null + null_rows)


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
