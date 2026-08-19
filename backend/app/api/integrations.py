"""Статус и проверка подключения внешних API: Ozon Seller/Performance
и сторонний аналитический сервис по конкурентам — видно, какие интеграции
настроены (без раскрытия самих секретов), и можно запустить тестовый
запрос к реальному внешнему сервису.
"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, request

from app.services import settings_store
from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError
from app.services.autoeuro_client import AutoEuroClient, AutoEuroError
from app.services.history import log_change
from app.services.moskvorechye_client import MoskvorechyeClient, MoskvorechyeError
from app.services.nomenclature_client import NomenclatureClient, NomenclatureClientError
from app.services.ozon_client import (
    DEFAULT_PERFORMANCE_API_BASE,
    DEFAULT_SELLER_API_BASE,
    OzonClient,
    OzonClientError,
)
from app.services.rossco_client import RosscoClient, RosscoError

bp = Blueprint("integrations", __name__)

SETTINGS_ENTITY_ID = 1  # синглтон — одна запись настроек на всё приложение


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


def _alfaauto_client() -> NomenclatureClient:
    cfg = current_app.config
    return NomenclatureClient(cfg["ALFAAUTO_BASE_URL"], cfg["ALFAAUTO_LOGIN"], cfg["ALFAAUTO_PASSWORD"])


def _rossco_client() -> RosscoClient:
    cfg = current_app.config
    return RosscoClient(cfg["ROSSCO_KEY1"], cfg["ROSSCO_KEY2"])


def _autoeuro_client() -> AutoEuroClient:
    return AutoEuroClient(current_app.config["AUTOEURO_API_KEY"])


def _moskvorechye_client() -> MoskvorechyeClient:
    cfg = current_app.config
    return MoskvorechyeClient(cfg["MOSKVORECHYE_BASE_URL"], cfg["MOSKVORECHYE_API_KEY"])


def _api_base_override(env_var: str, default: str) -> str | None:
    """Не None, если адрес API переопределён переменной окружения (обычно —
    забытая настройка на мок-сервер для тестирования, см.
    scripts/mock_ozon_api.py). Пока она задана, реальные ключи из UI не
    заработают — запросы всё равно идут по этому адресу."""
    value = os.environ.get(env_var)
    return value if value and value != default else None


@bp.get("/status")
def status():
    cfg = current_app.config
    integrations = [
        {
            "id": "ozon_seller",
            "name": "Ozon Seller API",
            "description": "Свои товары, цены и продажи (каталог, цены, аналитика продаж)",
            "configured": bool(cfg["OZON_CLIENT_ID"] and cfg["OZON_API_KEY"]),
            "api_base_override": _api_base_override("OZON_SELLER_API_BASE", DEFAULT_SELLER_API_BASE),
        },
        {
            "id": "ozon_performance",
            "name": "Ozon Performance API",
            "description": "Рекламный кабинет Ozon (OAuth2)",
            "configured": bool(cfg["OZON_PERFORMANCE_CLIENT_ID"] and cfg["OZON_PERFORMANCE_CLIENT_SECRET"]),
            "api_base_override": _api_base_override("OZON_PERFORMANCE_API_BASE", DEFAULT_PERFORMANCE_API_BASE),
        },
        {
            "id": "analytics",
            "name": "Аналитика конкурентов",
            "description": "Сторонний сервис цен конкурентов (провайдер уточняется с заказчиком)",
            "configured": bool(cfg["ANALYTICS_PROVIDER_BASE_URL"]),
            "api_base_override": None,
        },
        {
            "id": "alfaauto",
            "name": "1С: Альфа-Авто",
            "description": (
                "Номенклатура/остатки и нормо-часы напрямую из 1С (OData, логин/пароль пользователя 1С; "
                "без подключения обе работают по локальным загруженным таблицам)"
            ),
            "configured": bool(cfg["ALFAAUTO_BASE_URL"]),
            "api_base_override": None,
        },
        {
            "id": "rossco",
            "name": "Rossco",
            "description": "Поставщик запчастей — цены/наличие/кросс-номера по артикулу (SOAP api.rossko.ru)",
            "configured": bool(cfg["ROSSCO_KEY1"] and cfg["ROSSCO_KEY2"]),
            "api_base_override": None,
        },
        {
            "id": "autoeuro",
            "name": "АвтоЕвро",
            "description": "Поставщик запчастей — цены/наличие/кросс-номера по артикулу (REST api.autoeuro.ru)",
            "configured": bool(cfg["AUTOEURO_API_KEY"]),
            "api_base_override": None,
        },
        {
            "id": "moskvorechye",
            "name": "Москворечье",
            "description": (
                "Поставщик запчастей — цены/наличие/кросс-номера по артикулу (протокол ABCP). "
                "Нужен ещё базовый URL веб-службы — уточните у менеджера Москворечье."
            ),
            "configured": bool(cfg["MOSKVORECHYE_BASE_URL"] and cfg["MOSKVORECHYE_API_KEY"]),
            "api_base_override": None,
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
        elif integration_id == "alfaauto":
            message = _alfaauto_client().test_connection()
        elif integration_id == "rossco":
            message = _rossco_client().test_connection()
        elif integration_id == "autoeuro":
            message = _autoeuro_client().test_connection()
        elif integration_id == "moskvorechye":
            message = _moskvorechye_client().test_connection()
        else:
            return jsonify(error=f"Неизвестная интеграция: {integration_id}"), 404
    except (
        OzonClientError,
        AnalyticsProviderError,
        NomenclatureClientError,
        RosscoError,
        AutoEuroError,
        MoskvorechyeError,
    ) as exc:
        return jsonify(ok=False, message=str(exc))
    except Exception as exc:  # сеть/таймаут/и т.п. — тоже "не удалось", не 500
        current_app.logger.warning("test_connection(%s) failed: %s", integration_id, exc)
        return jsonify(ok=False, message=f"Не удалось подключиться: {exc}")

    return jsonify(ok=True, message=message)


@bp.post("/keys")
def save_keys():
    """Сохраняет ключи в базе данных (IntegrationSetting, переживает
    перезапуск, см. native_app.py) и сразу применяет их к текущему
    процессу — перезапускать приложение не нужно.

    Секреты никогда не возвращаются обратно клиенту — только записываются;
    сверить текущее значение нельзя, только заменить новым (см. GET /status
    для просто факта "настроено/нет").
    """
    body = request.get_json(force=True) or {}
    updates = {
        key: (body.get(key) or "").strip()
        for key in settings_store.ALLOWED_KEYS
        if (body.get(key) or "").strip()
    }
    if not updates:
        return jsonify(error="Нет данных для сохранения"), 400

    settings_store.save_keys(updates)

    for key, value in updates.items():
        os.environ[key] = value
        current_app.config[key] = value

    log_change(
        "integration_keys",
        SETTINGS_ENTITY_ID,
        "updated",
        details={"keys": sorted(updates.keys())},
    )
    return jsonify(ok=True, updated=sorted(updates.keys()))
