from app.extensions import db
from app.models import PriceSnapshot, Product
from app.services.llm_client import LLMClient
from app.services.ozon_client import OzonClient
from app.services.price_sync import sync_ozon_prices_job


def test_sync_creates_snapshot_and_history_entry(app, monkeypatch):
    with app.app_context():
        product = Product(ozon_product_id="ozon-1", sku="SKU-1", name="Товар", current_price=1000)
        db.session.add(product)
        db.session.commit()

        monkeypatch.setattr(
            OzonClient,
            "get_product_prices",
            lambda self: {"result": {"items": [{"offer_id": "SKU-1", "price": {"price": "1200"}}]}},
        )
        monkeypatch.setattr(OzonClient, "get_sales_stats", lambda self, *a, **kw: {})
        monkeypatch.setattr(
            LLMClient,
            "suggest_price",
            lambda self, product_data, snapshot_data: {"suggested_price": 1150, "reasoning": "тест"},
        )

        result = sync_ozon_prices_job()
        assert result == {"status": "ok", "snapshots_created": 1}

        snapshot = PriceSnapshot.query.filter_by(product_id=product.id).one()
        assert snapshot.suggested_price == 1150

        from app.services.history import query_history

        entries = query_history(entity_type="price_snapshot", entity_id=snapshot.id)
        assert len(entries) == 1
        assert entries[0].action == "created"
        assert entries[0].details["source"] == "scheduled_sync"
        assert entries[0].actor_id is None  # фоновая задача — не человек


def test_sync_skips_unknown_offer_ids(app, monkeypatch):
    with app.app_context():
        monkeypatch.setattr(
            OzonClient,
            "get_product_prices",
            lambda self: {"result": {"items": [{"offer_id": "NO-SUCH-SKU", "price": {"price": "100"}}]}},
        )
        monkeypatch.setattr(OzonClient, "get_sales_stats", lambda self, *a, **kw: {})

        result = sync_ozon_prices_job()
        assert result == {"status": "ok", "snapshots_created": 0}
