"""Бизнес-логика плановой подтяжки своих цен/продаж и рыночных данных,
формирования PriceSnapshot и предложения LLM по цене/карточке.

Ничего не применяется автоматически — снимок уходит в PricingDashboard
на approve/reject человеком (см. ARCHITECTURE.md, поток «Модуль 1»).

Вынесена из app/tasks/sync_ozon_prices.py в обычную функцию — вызывается
и из Celery beat (docker-compose режим), и из APScheduler в native_app.py
(однопроцессный режим без Docker). Требование: выполнять внутри app_context().
"""

from __future__ import annotations

from datetime import datetime, timedelta

from flask import current_app

from app.extensions import db
from app.models import PriceSnapshot, Product
from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError
from app.services.llm_client import LLMClient, LLMClientError
from app.services.ozon_client import OzonClient, OzonClientError


def sync_ozon_prices_job() -> dict:
    ozon = OzonClient(
        current_app.config["OZON_CLIENT_ID"],
        current_app.config["OZON_API_KEY"],
    )
    llm = LLMClient(current_app.config["LLM_SERVICE_URL"])

    try:
        analytics = AnalyticsProvider(
            current_app.config["ANALYTICS_PROVIDER_BASE_URL"],
            current_app.config["ANALYTICS_PROVIDER_API_KEY"],
        )
    except AnalyticsProviderError as exc:
        current_app.logger.warning("Пропускаем рыночные данные: %s", exc)
        analytics = None

    date_to = datetime.utcnow().date()
    date_from = date_to - timedelta(days=7)

    try:
        prices_resp = ozon.get_product_prices()
        ozon.get_sales_stats(str(date_from), str(date_to))
    except OzonClientError as exc:
        current_app.logger.error("Ozon Seller API недоступен: %s", exc)
        return {"status": "failed", "error": str(exc)}

    created = 0
    for item in prices_resp.get("result", {}).get("items", []):
        offer_id = item.get("offer_id")
        product = Product.query.filter_by(sku=offer_id).first()
        if not product:
            continue

        own_price = item.get("price", {}).get("price")

        competitor_data = {}
        if analytics:
            try:
                competitor_data = analytics.get_competitor_prices(product.name, product.category)
            except AnalyticsProviderError as exc:
                current_app.logger.warning("analytics provider error for %s: %s", product.sku, exc)

        snapshot = PriceSnapshot(
            product_id=product.id,
            own_price=own_price,
            competitor_min_price=competitor_data.get("min_price"),
            competitor_avg_price=competitor_data.get("avg_price"),
            competitor_raw_data=competitor_data.get("raw"),
        )

        try:
            suggestion = llm.suggest_price(
                {"name": product.name, "sku": product.sku, "cost_price": float(product.cost_price or 0)},
                {"own_price": own_price, **competitor_data},
            )
            snapshot.suggested_price = suggestion.get("suggested_price")
            snapshot.suggestion_reasoning = suggestion.get("reasoning")
        except LLMClientError as exc:
            current_app.logger.warning("LLM suggestion failed for %s: %s", product.sku, exc)

        db.session.add(snapshot)
        created += 1

    db.session.commit()
    return {"status": "ok", "snapshots_created": created}
