"""Статус и проверка подключения внешних API: Ozon Seller/Performance
и сторонний аналитический сервис по конкурентам.

Только администратор — здесь видно, какие интеграции настроены (без
раскрытия самих секретов), и можно запустить тестовый запрос к реальному
внешнему сервису (см. app/api/llm.py — тот же admin_required-паттерн).
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.auth import admin_required
from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError
from app.services.ozon_client import OzonClient, OzonClientError

bp = Blueprint("integrations", __name__)
bp.before_request(admin_required(lambda: None))


def _ozon_client() -> OzonClient:
    cfg = current_app.config
    return OzonClient(
        cfg["OZON_CLIENT_ID"],
        cfg["OZON_API_KEY"],
        cfg["OZON_PERFORMANCE_CLIENT_ID"],
        cfg["OZON_PERFORMANCE_CLIENT_SECRET"],
    )


def _analytics_provider() -> AnalyticsProvider:
    cfg = current_app.config
    return AnalyticsProvider(cfg["ANALYTICS_PROVIDER_BASE_URL"], cfg["ANALYTICS_PROVIDER_API_KEY"])


@bp.get("/status")
def status():
    cfg = current_app.config
    integrations = [
        {
            "id": "ozon_seller",
            "name": "Ozon Seller API",
            "description": "Свои товары, цены и продажи (каталог, цены, аналитика продаж)",
            "configured": bool(cfg["OZON_CLIENT_ID"] and cfg["OZON_API_KEY"]),
        },
        {
            "id": "ozon_performance",
            "name": "Ozon Performance API",
            "description": "Рекламный кабинет Ozon (OAuth2)",
            "configured": bool(cfg["OZON_PERFORMANCE_CLIENT_ID"] and cfg["OZON_PERFORMANCE_CLIENT_SECRET"]),
        },
        {
            "id": "analytics",
            "name": "Аналитика конкурентов",
            "description": "Сторонний сервис цен конкурентов (провайдер уточняется с заказчиком)",
            "configured": bool(cfg["ANALYTICS_PROVIDER_BASE_URL"]),
        },
    ]
    return jsonify(integrations)


@bp.post("/test/<integration_id>")
def test_connection(integration_id: str):
    try:
        if integration_id == "ozon_seller":
            message = _ozon_client().test_seller_connection()
        elif integration_id == "ozon_performance":
            message = _ozon_client().test_performance_connection()
        elif integration_id == "analytics":
            message = _analytics_provider().test_connection()
        else:
            return jsonify(error=f"Неизвестная интеграция: {integration_id}"), 404
    except (OzonClientError, AnalyticsProviderError) as exc:
        return jsonify(ok=False, message=str(exc))
    except Exception as exc:  # сеть/таймаут/и т.п. — тоже "не удалось", не 500
        current_app.logger.warning("test_connection(%s) failed: %s", integration_id, exc)
        return jsonify(ok=False, message=f"Не удалось подключиться: {exc}")

    return jsonify(ok=True, message=message)
