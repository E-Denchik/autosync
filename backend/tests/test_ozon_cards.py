import pytest

from app.extensions import db
from app.models import Product
from app.services.llm_client import LLMClient, LLMClientError


@pytest.fixture
def product(app):
    with app.app_context():
        p = Product(ozon_product_id="ozon-2", sku="SKU-2", name="Фильтр масляный", category="Двигатель")
        db.session.add(p)
        db.session.commit()
        return p.id


def test_list_products(client, admin_headers, product):
    resp = client.get("/api/ozon/cards", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


def test_update_cost_price(client, admin_headers, product):
    resp = client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": 850.5})
    assert resp.status_code == 200
    assert resp.get_json()["cost_price"] == 850.5


def test_update_cost_price_logs_history(client, admin_headers, product):
    client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": 300})

    history_resp = client.get(
        f"/api/history?entity_type=product&entity_id={product}", headers=admin_headers
    )
    entries = history_resp.get_json()
    assert len(entries) == 1
    assert entries[0]["action"] == "edited"
    assert entries[0]["actor_email"] == "admin@test.local"


def test_update_cost_price_accepts_null_to_clear(client, admin_headers, product):
    client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": 300})
    resp = client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": None})
    assert resp.status_code == 200
    assert resp.get_json()["cost_price"] is None


def test_update_cost_price_rejects_negative(client, admin_headers, product):
    resp = client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": -5})
    assert resp.status_code == 400


def test_update_cost_price_rejects_non_numeric(client, admin_headers, product):
    resp = client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": "abc"})
    assert resp.status_code == 400


def test_update_cost_price_rejects_other_fields(client, admin_headers, product):
    resp = client.patch(
        f"/api/ozon/cards/{product}", headers=admin_headers, json={"cost_price": 100, "name": "hijack"}
    )
    assert resp.status_code == 400


def test_update_cost_price_requires_field(client, admin_headers, product):
    resp = client.patch(f"/api/ozon/cards/{product}", headers=admin_headers, json={})
    assert resp.status_code == 400


def test_update_cost_price_requires_auth(client, product):
    resp = client.patch(f"/api/ozon/cards/{product}", json={"cost_price": 100})
    assert resp.status_code == 401


def test_update_cost_price_unknown_product_404(client, admin_headers):
    resp = client.patch("/api/ozon/cards/99999", headers=admin_headers, json={"cost_price": 100})
    assert resp.status_code == 404


def test_generate_card_passes_top_listings_to_llm_and_returns_them(
    client, admin_headers, product, monkeypatch
):
    """generate_card должен не просто спрашивать LLM о цене конкурентов, а
    передавать список топовых конкурентных карточек (что продаётся лучше) и
    возвращать его фронту — иначе не выполняется требование заказчика
    'анализировал, какие карточки лучше продают'."""
    captured = {}

    class FakeProvider:
        def __init__(self, base_url, api_key):
            pass

        def get_competitor_prices(self, name, category):
            return {"min_price": 900, "avg_price": 1100, "max_price": 1400, "sample_size": 5}

        def get_top_competitor_listings(self, name, category):
            return [{"name": "Конкурент А", "price": 950, "sales_rank": 1, "units_sold_30d": 500,
                      "rating": 4.9, "reviews_count": 80}]

    class FakeLLMClient:
        def __init__(self, base_url):
            pass

        def generate_card_content(self, product_data, market):
            captured["product"] = product_data
            captured["market"] = market
            return {"title": "т", "bullets": [], "description": "d", "suggested_price": 950, "reasoning": "r"}

    monkeypatch.setattr("app.api.ozon.cards.AnalyticsProvider", FakeProvider)
    monkeypatch.setattr("app.api.ozon.cards.LLMClient", FakeLLMClient)

    resp = client.post(f"/api/ozon/cards/{product}/generate", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()

    assert captured["market"]["top_listings"][0]["name"] == "Конкурент А"
    assert captured["market"]["price_stats"]["min_price"] == 900
    assert body["competitor_listings"] == [
        {"name": "Конкурент А", "price": 950, "sales_rank": 1, "units_sold_30d": 500,
         "rating": 4.9, "reviews_count": 80}
    ]
    assert body["suggested_price"] == 950


def test_generate_card_survives_analytics_provider_unavailable(client, admin_headers, product, monkeypatch):
    """analytics provider не настроен/недоступен — генерация карточки всё
    равно должна работать (без рыночных данных), а не падать 500."""
    from app.services.analytics_provider import AnalyticsProviderError

    class FailingProvider:
        def __init__(self, base_url, api_key):
            pass

        def get_competitor_prices(self, name, category):
            raise AnalyticsProviderError("не настроен")

        def get_top_competitor_listings(self, name, category):
            raise AnalyticsProviderError("не настроен")

    class FakeLLMClient:
        def __init__(self, base_url):
            pass

        def generate_card_content(self, product_data, market):
            assert market == {"price_stats": None, "top_listings": []}
            return {"title": "т", "bullets": [], "description": "d", "suggested_price": None, "reasoning": "r"}

    monkeypatch.setattr("app.api.ozon.cards.AnalyticsProvider", FailingProvider)
    monkeypatch.setattr("app.api.ozon.cards.LLMClient", FakeLLMClient)

    resp = client.post(f"/api/ozon/cards/{product}/generate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["competitor_listings"] == []


def test_generate_card_returns_502_when_llm_unavailable(client, admin_headers, product, monkeypatch):
    from app.services.llm_client import LLMClientError

    class FakeProvider:
        def __init__(self, base_url, api_key):
            pass

        def get_competitor_prices(self, name, category):
            return {}

        def get_top_competitor_listings(self, name, category):
            return []

    class FailingLLMClient:
        def __init__(self, base_url):
            pass

        def generate_card_content(self, product_data, market):
            raise LLMClientError("llm-service недоступен")

    monkeypatch.setattr("app.api.ozon.cards.AnalyticsProvider", FakeProvider)
    monkeypatch.setattr("app.api.ozon.cards.LLMClient", FailingLLMClient)

    resp = client.post(f"/api/ozon/cards/{product}/generate", headers=admin_headers)
    assert resp.status_code == 502


def test_sync_endpoint_returns_ok_false_when_not_configured(client, admin_headers):
    resp = client.post("/api/ozon/cards/sync", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "OZON_CLIENT_ID" in body["message"]


def test_sync_endpoint_returns_created_updated_counts(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.ozon.cards.sync_ozon_catalog_job",
        lambda: {"status": "ok", "created": 3, "updated": 1},
    )
    resp = client.post("/api/ozon/cards/sync", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"ok": True, "created": 3, "updated": 1}


def test_sync_endpoint_unreachable_server_returns_ok_false_not_500(client, admin_headers, monkeypatch):
    """Регрессия: Ozon (или мок-сервер для теста) недоступен по сети —
    раньше это была необработанная requests.exceptions.ConnectionError,
    отдававшая клиенту голый 500 вместо понятного сообщения."""
    import requests

    app_config_updates = {"OZON_CLIENT_ID": "cid", "OZON_API_KEY": "key"}

    def fake_post(url, json=None, headers=None, timeout=None):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("app.services.ozon_client.requests.post", fake_post)

    # выставляем ключи через тот же endpoint, что и реальный UI
    client.post("/api/integrations/keys", headers=admin_headers, json=app_config_updates)

    resp = client.post("/api/ozon/cards/sync", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "недоступен" in body["message"]


def test_generate_card_success(client, admin_headers, product, monkeypatch):
    monkeypatch.setattr(
        LLMClient,
        "generate_card_content",
        lambda self, product_data, competitor_cards: {
            "title": "Тестовая карточка",
            "bullets": ["пункт 1"],
        },
    )
    resp = client.post(f"/api/ozon/cards/{product}/generate", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["title"] == "Тестовая карточка"


def test_generate_card_returns_502_when_llm_unavailable(client, admin_headers, product, monkeypatch):
    def _raise(self, product_data, competitor_cards):
        raise LLMClientError("llm-service недоступен")

    monkeypatch.setattr(LLMClient, "generate_card_content", _raise)
    resp = client.post(f"/api/ozon/cards/{product}/generate", headers=admin_headers)
    assert resp.status_code == 502


def test_cards_require_auth(client):
    resp = client.get("/api/ozon/cards")
    assert resp.status_code == 401


@pytest.fixture
def catalog(app):
    with app.app_context():
        db.session.add_all(
            [
                Product(ozon_product_id="ozon-10", sku="BRK-1", name="Тормозной диск", category="Тормозная система"),
                Product(ozon_product_id="ozon-11", sku="BRK-2", name="Тормозная колодка", category="Тормозная система"),
                Product(ozon_product_id="ozon-12", sku="ENG-1", name="Масляный фильтр", category="Двигатель"),
                Product(ozon_product_id="ozon-13", sku="MISC-1", name="Товар без категории", category=None),
            ]
        )
        db.session.commit()


def test_list_categories(client, admin_headers, catalog):
    resp = client.get("/api/ozon/cards/categories", headers=admin_headers)
    assert resp.status_code == 200
    body = {row["category"]: row["count"] for row in resp.get_json()}
    assert body == {"Тормозная система": 2, "Двигатель": 1, None: 1}


def test_list_products_filters_by_category(client, admin_headers, catalog):
    resp = client.get("/api/ozon/cards?category=Двигатель", headers=admin_headers)
    body = resp.get_json()
    assert len(body) == 1
    assert body[0]["sku"] == "ENG-1"


def test_list_products_filters_by_uncategorized(client, admin_headers, catalog):
    resp = client.get("/api/ozon/cards?category=__uncategorized__", headers=admin_headers)
    body = resp.get_json()
    assert len(body) == 1
    assert body[0]["sku"] == "MISC-1"


def test_list_products_search_matches_name_or_sku(client, admin_headers, catalog):
    resp = client.get("/api/ozon/cards?q=тормозной", headers=admin_headers)
    skus = {row["sku"] for row in resp.get_json()}
    assert skus == {"BRK-1"}

    resp2 = client.get("/api/ozon/cards?q=BRK-2", headers=admin_headers)
    skus2 = {row["sku"] for row in resp2.get_json()}
    assert skus2 == {"BRK-2"}


def test_list_products_search_and_category_combine(client, admin_headers, catalog):
    resp = client.get("/api/ozon/cards?category=Тормозная система&q=колодка", headers=admin_headers)
    skus = {row["sku"] for row in resp.get_json()}
    assert skus == {"BRK-2"}
