from app.extensions import db
from app.models import Product
from app.services.catalog_sync import sync_ozon_catalog_job
from app.services.ozon_client import OzonClient


def test_sync_fails_cleanly_without_credentials(app):
    with app.app_context():
        result = sync_ozon_catalog_job()
        assert result["status"] == "failed"
        assert "OZON_CLIENT_ID" in result["error"]


def test_sync_creates_new_products(app, monkeypatch):
    with app.app_context():
        app.config["OZON_CLIENT_ID"] = "cid"
        app.config["OZON_API_KEY"] = "key"

        pages = [
            {"result": {"items": [{"product_id": 111, "offer_id": "SKU-1"}], "last_id": ""}},
        ]
        monkeypatch.setattr(OzonClient, "list_products", lambda self, last_id="", limit=100: pages[0])
        monkeypatch.setattr(
            OzonClient,
            "get_product_info",
            lambda self, product_ids: {
                "result": {
                    "items": [{"product_id": 111, "name": "Тормозной диск", "category": "Тормозная система"}]
                }
            },
        )
        monkeypatch.setattr(
            OzonClient,
            "get_product_prices",
            lambda self, offer_ids=None: {"result": {"items": [{"offer_id": "SKU-1", "price": {"price": "1200"}}]}},
        )

        result = sync_ozon_catalog_job()
        assert result == {"status": "ok", "created": 1, "updated": 0}

        product = Product.query.filter_by(ozon_product_id="111").one()
        assert product.sku == "SKU-1"
        assert product.name == "Тормозной диск"
        assert product.category == "Тормозная система"
        assert float(product.current_price) == 1200.0

        from app.services.history import query_history

        entries = query_history(entity_type="product", entity_id=product.id)
        assert len(entries) == 1
        assert entries[0].action == "created"
        assert entries[0].details["source"] == "ozon_sync"


def test_sync_updates_existing_product_matched_by_ozon_product_id(app, monkeypatch):
    with app.app_context():
        app.config["OZON_CLIENT_ID"] = "cid"
        app.config["OZON_API_KEY"] = "key"

        existing = Product(ozon_product_id="222", sku="SKU-OLD", name="Старое имя", current_price=100)
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

        monkeypatch.setattr(
            OzonClient,
            "list_products",
            lambda self, last_id="", limit=100: {
                "result": {"items": [{"product_id": 222, "offer_id": "SKU-NEW"}], "last_id": ""}
            },
        )
        monkeypatch.setattr(
            OzonClient,
            "get_product_info",
            lambda self, product_ids: {"result": {"items": [{"product_id": 222, "name": "Новое имя"}]}},
        )
        monkeypatch.setattr(
            OzonClient,
            "get_product_prices",
            lambda self, offer_ids=None: {"result": {"items": [{"offer_id": "SKU-NEW", "price": {"price": "150"}}]}},
        )

        result = sync_ozon_catalog_job()
        assert result == {"status": "ok", "created": 0, "updated": 1}

        product = Product.query.get(existing_id)
        assert product.sku == "SKU-NEW"
        assert product.name == "Новое имя"
        assert float(product.current_price) == 150.0


def test_sync_skips_update_when_nothing_changed(app, monkeypatch):
    with app.app_context():
        app.config["OZON_CLIENT_ID"] = "cid"
        app.config["OZON_API_KEY"] = "key"

        existing = Product(ozon_product_id="333", sku="SKU-3", name="Товар", current_price=500)
        db.session.add(existing)
        db.session.commit()

        monkeypatch.setattr(
            OzonClient,
            "list_products",
            lambda self, last_id="", limit=100: {
                "result": {"items": [{"product_id": 333, "offer_id": "SKU-3"}], "last_id": ""}
            },
        )
        monkeypatch.setattr(
            OzonClient,
            "get_product_info",
            lambda self, product_ids: {"result": {"items": [{"product_id": 333, "name": "Товар"}]}},
        )
        monkeypatch.setattr(
            OzonClient,
            "get_product_prices",
            lambda self, offer_ids=None: {"result": {"items": [{"offer_id": "SKU-3", "price": {"price": "500"}}]}},
        )

        result = sync_ozon_catalog_job()
        assert result == {"status": "ok", "created": 0, "updated": 0}


def test_sync_paginates_using_last_id(app, monkeypatch):
    with app.app_context():
        app.config["OZON_CLIENT_ID"] = "cid"
        app.config["OZON_API_KEY"] = "key"

        pages = [
            {"result": {"items": [{"product_id": 1, "offer_id": "A"}], "last_id": "page2"}},
            {"result": {"items": [{"product_id": 2, "offer_id": "B"}], "last_id": ""}},
        ]
        calls = {"n": 0}

        def fake_list_products(self, last_id="", limit=100):
            page = pages[calls["n"]]
            calls["n"] += 1
            return page

        monkeypatch.setattr(OzonClient, "list_products", fake_list_products)
        monkeypatch.setattr(OzonClient, "get_product_info", lambda self, product_ids: {"result": {"items": []}})
        monkeypatch.setattr(
            OzonClient, "get_product_prices", lambda self, offer_ids=None: {"result": {"items": []}}
        )

        result = sync_ozon_catalog_job()
        assert result == {"status": "ok", "created": 2, "updated": 0}
        assert calls["n"] == 2
        assert {p.sku for p in Product.query.all()} == {"A", "B"}
