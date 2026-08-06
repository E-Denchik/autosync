from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.auth import get_current_user, login_required
from app.extensions import db
from app.models import PriceSnapshot, PriceSuggestionStatus, Product
from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError
from app.services.history import log_change
from app.services.llm_client import LLMClient, LLMClientError

bp = Blueprint("ozon_pricing", __name__)
bp.before_request(login_required(lambda: None))


def _serialize(snapshot: PriceSnapshot) -> dict:
    return {
        "id": snapshot.id,
        "product_id": snapshot.product_id,
        "product_name": snapshot.product.name if snapshot.product else None,
        "own_price": float(snapshot.own_price) if snapshot.own_price is not None else None,
        "own_position": snapshot.own_position,
        "competitor_min_price": float(snapshot.competitor_min_price)
        if snapshot.competitor_min_price is not None
        else None,
        "competitor_avg_price": float(snapshot.competitor_avg_price)
        if snapshot.competitor_avg_price is not None
        else None,
        "suggested_price": float(snapshot.suggested_price) if snapshot.suggested_price is not None else None,
        "suggestion_reasoning": snapshot.suggestion_reasoning,
        "status": snapshot.status.value,
        "created_at": snapshot.created_at.isoformat(),
    }


@bp.get("")
def list_snapshots():
    status = request.args.get("status", PriceSuggestionStatus.PENDING.value)
    query = PriceSnapshot.query
    if status != "all":
        query = query.filter(PriceSnapshot.status == PriceSuggestionStatus(status))
    snapshots = query.order_by(PriceSnapshot.created_at.desc()).limit(200).all()
    return jsonify([_serialize(s) for s in snapshots])


@bp.post("/<int:snapshot_id>/approve")
def approve_snapshot(snapshot_id: int):
    snapshot = db.get_or_404(PriceSnapshot, snapshot_id)
    snapshot.status = PriceSuggestionStatus.APPROVED
    snapshot.reviewed_at = datetime.utcnow()

    if snapshot.suggested_price is not None:
        product = db.session.get(Product, snapshot.product_id)
        if product:
            product.current_price = snapshot.suggested_price
        # Применение цены в Ozon — отдельный шаг через ozon_client.update_prices,
        # намеренно НЕ вызывается автоматически здесь. См. ARCHITECTURE.md:
        # "Человек в контуре на изменении цен".

    log_change(
        "price_snapshot",
        snapshot.id,
        "approved",
        actor=get_current_user(),
        details={"suggested_price": float(snapshot.suggested_price) if snapshot.suggested_price else None},
    )
    db.session.commit()
    return jsonify(_serialize(snapshot))


@bp.post("/<int:snapshot_id>/reject")
def reject_snapshot(snapshot_id: int):
    snapshot = db.get_or_404(PriceSnapshot, snapshot_id)
    snapshot.status = PriceSuggestionStatus.REJECTED
    snapshot.reviewed_at = datetime.utcnow()
    log_change("price_snapshot", snapshot.id, "rejected", actor=get_current_user())
    db.session.commit()
    return jsonify(_serialize(snapshot))


@bp.post("/analyze/<int:product_id>")
def analyze_product(product_id: int):
    """Разовый ручной запуск анализа цены по одному товару — то же самое,
    что делает плановая задача tasks.sync_ozon_prices для всех товаров,
    только без похода в Ozon Seller API (используется текущая сохранённая
    цена товара). Удобно для проверки предложения без ожидания расписания
    и без реальных ключей Ozon/аналитики.
    """
    product = db.get_or_404(Product, product_id)

    competitor_data = {}
    try:
        provider = AnalyticsProvider(
            current_app.config["ANALYTICS_PROVIDER_BASE_URL"],
            current_app.config["ANALYTICS_PROVIDER_API_KEY"],
        )
        competitor_data = provider.get_competitor_prices(product.name, product.category)
    except AnalyticsProviderError as exc:
        current_app.logger.info("analytics provider unavailable, analyzing on own price only: %s", exc)

    snapshot = PriceSnapshot(
        product_id=product.id,
        own_price=product.current_price,
        competitor_min_price=competitor_data.get("min_price"),
        competitor_avg_price=competitor_data.get("avg_price"),
        competitor_raw_data=competitor_data.get("raw"),
    )

    llm = LLMClient(current_app.config["LLM_SERVICE_URL"])
    try:
        suggestion = llm.suggest_price(
            {
                "name": product.name,
                "sku": product.sku,
                "cost_price": float(product.cost_price) if product.cost_price else None,
            },
            {"own_price": float(product.current_price) if product.current_price else None, **competitor_data},
        )
        snapshot.suggested_price = suggestion.get("suggested_price")
        snapshot.suggestion_reasoning = suggestion.get("reasoning")
    except LLMClientError as exc:
        return jsonify(error=f"LLM-сервис недоступен: {exc}"), 502

    db.session.add(snapshot)
    db.session.flush()
    log_change(
        "price_snapshot",
        snapshot.id,
        "created",
        actor=get_current_user(),
        details={"product_id": product.id, "suggested_price": snapshot.suggested_price},
    )
    db.session.commit()
    return jsonify(_serialize(snapshot)), 201
