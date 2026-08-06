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


def test_create_product_requires_sku_and_name(client, admin_headers):
    resp = client.post("/api/ozon/cards", headers=admin_headers, json={"sku": "X"})
    assert resp.status_code == 400


def test_create_product(client, admin_headers):
    resp = client.post(
        "/api/ozon/cards",
        headers=admin_headers,
        json={"sku": "SKU-3", "name": "Свеча зажигания", "current_price": 250},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["sku"] == "SKU-3"
    assert body["current_price"] == 250.0


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
