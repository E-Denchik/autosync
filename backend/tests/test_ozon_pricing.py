import pytest

from app.extensions import db
from app.models import PriceSnapshot, PriceSuggestionStatus, Product
from app.services.llm_client import LLMClient, LLMClientError


@pytest.fixture
def product(app):
    with app.app_context():
        p = Product(
            ozon_product_id="ozon-1",
            sku="SKU-1",
            name="Тормозной диск",
            category="Тормозная система",
            cost_price=800,
            current_price=1500,
        )
        db.session.add(p)
        db.session.commit()
        return p.id


@pytest.fixture
def snapshot(app, product):
    with app.app_context():
        s = PriceSnapshot(
            product_id=product,
            own_price=1500,
            suggested_price=1400,
            status=PriceSuggestionStatus.PENDING,
        )
        db.session.add(s)
        db.session.commit()
        return s.id


def test_list_snapshots_defaults_to_pending(client, admin_headers, snapshot):
    resp = client.get("/api/ozon/pricing", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 1
    assert body[0]["status"] == "pending"


def test_list_snapshots_filters_by_status(client, admin_headers, snapshot):
    resp = client.get("/api/ozon/pricing?status=approved", headers=admin_headers)
    assert resp.get_json() == []


def test_approve_snapshot_applies_suggested_price_to_product(
    client, admin_headers, snapshot, product, app
):
    resp = client.post(f"/api/ozon/pricing/{snapshot}/approve", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "approved"

    with app.app_context():
        p = db.session.get(Product, product)
        assert float(p.current_price) == 1400.0


def test_reject_snapshot(client, admin_headers, snapshot):
    resp = client.post(f"/api/ozon/pricing/{snapshot}/reject", headers=admin_headers)
    assert resp.get_json()["status"] == "rejected"


def test_analyze_product_without_analytics_provider_still_works(
    client, admin_headers, product, monkeypatch
):
    # ANALYTICS_PROVIDER_BASE_URL пуст по умолчанию — провайдер сам откажет,
    # analyze всё равно должен отработать на своей цене.
    monkeypatch.setattr(
        LLMClient,
        "suggest_price",
        lambda self, product_data, snapshot_data: {
            "suggested_price": 1350,
            "reasoning": "тестовое обоснование",
        },
    )
    resp = client.post(f"/api/ozon/pricing/analyze/{product}", headers=admin_headers)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["suggested_price"] == 1350
    assert body["suggestion_reasoning"] == "тестовое обоснование"


def test_analyze_product_returns_502_when_llm_unavailable(client, admin_headers, product, monkeypatch):
    def _raise(self, product_data, snapshot_data):
        raise LLMClientError("llm-service недоступен")

    monkeypatch.setattr(LLMClient, "suggest_price", _raise)
    resp = client.post(f"/api/ozon/pricing/analyze/{product}", headers=admin_headers)
    assert resp.status_code == 502


def test_pricing_requires_auth(client, snapshot):
    resp = client.get("/api/ozon/pricing")
    assert resp.status_code == 401
