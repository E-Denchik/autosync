import uuid

from flask import Blueprint, current_app, jsonify, request

from app.auth import get_current_user, login_required
from app.extensions import db
from app.models import Product
from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError
from app.services.history import log_change
from app.services.llm_client import LLMClient, LLMClientError

bp = Blueprint("ozon_cards", __name__)
bp.before_request(login_required(lambda: None))


def _serialize_product(p: Product) -> dict:
    return {
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "category": p.category,
        "cost_price": float(p.cost_price) if p.cost_price is not None else None,
        "current_price": float(p.current_price) if p.current_price is not None else None,
    }


@bp.post("/<int:product_id>/generate")
def generate_card(product_id: int):
    """Генерирует SEO-текст/буллеты/характеристики карточки на основе
    анализа топовых конкурентных карточек. Ничего не публикует в Ozon
    автоматически — результат возвращается фронту для проверки.
    """
    product = db.get_or_404(Product, product_id)

    competitor_cards = []
    try:
        provider = AnalyticsProvider(
            current_app.config["ANALYTICS_PROVIDER_BASE_URL"],
            current_app.config["ANALYTICS_PROVIDER_API_KEY"],
        )
        competitor_cards = [provider.get_competitor_prices(product.name, product.category)]
    except AnalyticsProviderError as exc:
        current_app.logger.warning("analytics provider unavailable: %s", exc)

    llm = LLMClient(current_app.config["LLM_SERVICE_URL"])
    try:
        content = llm.generate_card_content(
            {"name": product.name, "sku": product.sku, "category": product.category},
            competitor_cards,
        )
    except LLMClientError as exc:
        return jsonify(error=f"LLM-сервис недоступен: {exc}"), 502
    return jsonify(content)


@bp.get("")
def list_products():
    products = Product.query.order_by(Product.updated_at.desc()).limit(200).all()
    return jsonify([_serialize_product(p) for p in products])


@bp.post("")
def create_product():
    """Ручное добавление товара — пока не подключён Ozon Seller API,
    это единственный способ завести товар для теста генерации карточек
    и анализа цены.
    """
    body = request.get_json(force=True) or {}
    sku = (body.get("sku") or "").strip()
    name = (body.get("name") or "").strip()
    if not sku or not name:
        return jsonify(error="'sku' и 'name' обязательны"), 400

    product = Product(
        ozon_product_id=body.get("ozon_product_id") or f"manual-{uuid.uuid4().hex[:12]}",
        sku=sku,
        name=name,
        category=body.get("category"),
        cost_price=body.get("cost_price"),
        current_price=body.get("current_price"),
    )
    db.session.add(product)
    db.session.flush()
    log_change(
        "product",
        product.id,
        "created",
        actor=get_current_user(),
        details={"sku": sku, "name": name},
    )
    db.session.commit()
    return jsonify(_serialize_product(product)), 201
