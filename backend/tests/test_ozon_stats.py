import pytest

from app.extensions import db
from app.models import PriceSnapshot, Product


@pytest.fixture
def products(app):
    with app.app_context():
        cheap = Product(
            ozon_product_id="ozon-1",
            sku="SKU-1",
            name="Тормозной диск",
            category="Тормозная система",
            current_price=1000,
            units_sold_7d=20,
            revenue_7d=20000,
        )
        expensive_slow = Product(
            ozon_product_id="ozon-2",
            sku="SKU-2",
            name="Амортизатор",
            category="Подвеска",
            current_price=5000,
            units_sold_7d=1,
            revenue_7d=5000,
        )
        no_stats = Product(
            ozon_product_id="ozon-3",
            sku="SKU-3",
            name="Без статистики",
            current_price=None,
        )
        db.session.add_all([cheap, expensive_slow, no_stats])
        db.session.commit()

        db.session.add(
            PriceSnapshot(
                product_id=cheap.id,
                own_price=1000,
                competitor_min_price=900,
                competitor_avg_price=950,
            )
        )
        db.session.add(
            PriceSnapshot(
                product_id=expensive_slow.id,
                own_price=4500,
                competitor_min_price=4000,
                competitor_avg_price=4200,
            )
        )
        # более свежий снимок для expensive_slow — должен победить более старый
        db.session.add(
            PriceSnapshot(
                product_id=expensive_slow.id,
                own_price=5000,
                competitor_min_price=4100,
                competitor_avg_price=4300,
            )
        )
        db.session.commit()
        return {"cheap": cheap.id, "expensive_slow": expensive_slow.id, "no_stats": no_stats.id}


def test_products_returns_all_with_market_position(client, admin_headers, products):
    resp = client.get("/api/ozon/stats/products", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 3

    by_id = {row["id"]: row for row in body}
    cheap = by_id[products["cheap"]]
    assert cheap["price_position"] == "above_avg"  # 1000 > конкурент. средняя 950
    assert cheap["units_sold_7d"] == 20
    assert cheap["revenue_7d"] == 20000.0

    expensive = by_id[products["expensive_slow"]]
    assert expensive["competitor_min_price"] == 4100.0  # взят самый свежий снимок
    assert expensive["competitor_avg_price"] == 4300.0
    assert expensive["price_position"] == "above_avg"

    no_stats = by_id[products["no_stats"]]
    assert no_stats["price_position"] == "no_data"
    assert no_stats["current_price"] is None


def test_products_sorts_by_field_desc_by_default(client, admin_headers, products):
    resp = client.get("/api/ozon/stats/products?sort=current_price", headers=admin_headers)
    body = resp.get_json()
    prices = [row["current_price"] for row in body]
    assert prices == [5000.0, 1000.0, None]  # убывание, None — в конце


def test_products_sorts_ascending(client, admin_headers, products):
    resp = client.get("/api/ozon/stats/products?sort=units_sold_7d&order=asc", headers=admin_headers)
    body = resp.get_json()
    sold = [row["units_sold_7d"] for row in body]
    assert sold == [1, 20, None]


def test_products_rejects_unknown_sort_field_by_falling_back(client, admin_headers, products):
    resp = client.get("/api/ozon/stats/products?sort=not_a_real_field", headers=admin_headers)
    assert resp.status_code == 200  # тихо откатывается на дефолтную сортировку, не 400
