from app.extensions import db
from app.models import (
    Contract,
    ConfidenceLevel,
    DocumentProcessingStatus,
    LaborLine,
    PartMatch,
    PriceSnapshot,
    PriceSuggestionStatus,
    Product,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard/summary").status_code == 401


def test_dashboard_summary_empty_state(client, admin_headers):
    resp = client.get("/api/dashboard/summary", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["products_total"] == 0
    assert body["pending_labor_lines"] == 0
    assert body["recent_repair_orders"] == []
    assert body["recent_price_suggestions"] == []
    assert body["llm_model"] is None


def test_dashboard_summary_reflects_real_data(client, admin_headers, app):
    with app.app_context():
        product = Product(ozon_product_id="o1", sku="S1", name="Товар", current_price=100)
        db.session.add(product)
        db.session.flush()

        db.session.add(
            PriceSnapshot(
                product_id=product.id,
                own_price=100,
                suggested_price=90,
                status=PriceSuggestionStatus.PENDING,
            )
        )

        contract = Contract(
            original_filename="c.xlsx", storage_path="/tmp/c.xlsx", status=DocumentProcessingStatus.PARSED
        )
        db.session.add(contract)
        db.session.flush()

        order = RepairOrder(
            contract_id=contract.id,
            original_filename="o.xlsx",
            storage_path="/tmp/o.xlsx",
            status=RepairOrderStatus.NEEDS_REVIEW,
        )
        db.session.add(order)
        db.session.flush()

        db.session.add(
            PartMatch(
                repair_order_id=order.id,
                contract_article="A1",
                contract_name="Деталь",
                confidence_level=ConfidenceLevel.LLM_GUESS,
                review_status=ReviewStatus.PENDING,
            )
        )
        db.session.add(
            LaborLine(
                repair_order_id=order.id,
                description="Замена колодок",
                confidence_level=ConfidenceLevel.LLM_GUESS,
                review_status=ReviewStatus.PENDING,
            )
        )
        db.session.commit()

    resp = client.get("/api/dashboard/summary", headers=admin_headers)
    body = resp.get_json()
    assert body["products_total"] == 1
    assert body["pending_price_suggestions"] == 1
    assert body["repair_orders_needs_review"] == 1
    assert body["pending_part_matches"] == 1
    assert body["pending_labor_lines"] == 1
    assert len(body["recent_repair_orders"]) == 1
    recent_order = body["recent_repair_orders"][0]
    assert recent_order["status"] == "needs_review"
    assert recent_order["matches_total"] == 1
    assert recent_order["matches_pending"] == 1
    assert recent_order["labor_total"] == 1
    assert recent_order["labor_pending"] == 1
    assert len(body["recent_price_suggestions"]) == 1
    assert body["recent_price_suggestions"][0]["suggested_price"] == 90.0


def test_dashboard_reports_selected_llm_model(client, admin_headers, monkeypatch):
    from app.services.llm_client import LLMClient

    monkeypatch.setattr(
        LLMClient,
        "list_models",
        lambda self: {"providers": {"ollama": {"available": True, "models": [{"name": "llama3.2:3b"}]}}},
    )
    client.post(
        "/api/llm/select", headers=admin_headers, json={"provider": "ollama", "model": "llama3.2:3b"}
    )

    resp = client.get("/api/dashboard/summary", headers=admin_headers)
    assert resp.get_json()["llm_model"] == {"provider": "ollama", "model": "llama3.2:3b"}
