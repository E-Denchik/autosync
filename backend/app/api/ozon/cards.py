from flask import Blueprint, current_app, jsonify, request

from app.auth import get_current_user, login_required
from app.extensions import db
from app.models import Product
from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError
from app.services.catalog_sync import sync_ozon_catalog_job
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


@bp.get("/categories")
def list_categories():
    """Категории для навигации по каталогу — не отдельная таблица, а
    группировка по Product.category (заполняется синхронизацией с Ozon,
    см. services/catalog_sync.py)."""
    rows = (
        db.session.query(Product.category, db.func.count(Product.id))
        .group_by(Product.category)
        .order_by(Product.category.is_(None), Product.category)
        .all()
    )
    return jsonify([{"category": category, "count": count} for category, count in rows])


@bp.get("")
def list_products():
    query = Product.query

    category = request.args.get("category")
    if category == "__uncategorized__":
        query = query.filter(Product.category.is_(None))
    elif category:
        query = query.filter(Product.category == category)

    q = (request.args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(Product.name.ilike(like), Product.sku.ilike(like)))

    products = query.order_by(Product.updated_at.desc()).limit(200).all()
    return jsonify([_serialize_product(p) for p in products])


@bp.patch("/<int:product_id>")
def update_product(product_id: int):
    """Закупочная цена — единственное поле, которое можно менять здесь:
    Ozon Seller API её не предоставляет (это внутренняя себестоимость
    продавца, не то, что продаётся), а без неё LLM не может учитывать
    маржу при предложении цены (см. services/price_sync.py). Название,
    SKU, категория и текущая цена приходят только из синхронизации с
    Ozon и здесь не редактируются.
    """
    product = db.get_or_404(Product, product_id)
    body = request.get_json(force=True) or {}
    if set(body.keys()) - {"cost_price"}:
        return jsonify(error="Разрешено изменять только 'cost_price'"), 400
    if "cost_price" not in body:
        return jsonify(error="'cost_price' обязателен"), 400

    raw = body["cost_price"]
    try:
        cost_price = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify(error="'cost_price' должно быть числом"), 400
    if cost_price is not None and cost_price < 0:
        return jsonify(error="'cost_price' не может быть отрицательной"), 400

    product.cost_price = cost_price
    log_change(
        "product",
        product.id,
        "edited",
        actor=get_current_user(),
        details={"cost_price": cost_price},
    )
    db.session.commit()
    return jsonify(_serialize_product(product))


@bp.post("/sync")
def sync_catalog():
    """Ручной запуск синхронизации каталога с Ozon Seller API (то же самое,
    что делает плановая задача раз в 6 часов, см. native_app.py). Товары
    заводятся и обновляются только отсюда — ручного добавления через форму
    больше нет, единственный источник каталога — Ozon.
    """
    try:
        result = sync_ozon_catalog_job()
    except Exception as exc:  # неожиданный формат ответа Ozon и т.п. — тоже "не удалось", не 500
        current_app.logger.exception("Ozon catalog sync упал неожиданно")
        return jsonify(ok=False, message=f"Не удалось синхронизировать: {exc}")
    if result["status"] == "failed":
        return jsonify(ok=False, message=result["error"])
    return jsonify(ok=True, created=result["created"], updated=result["updated"])
