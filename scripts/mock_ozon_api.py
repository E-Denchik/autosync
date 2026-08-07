"""Локальный мок Ozon Seller API — для проверки синхронизации каталога
(app/services/catalog_sync.py) без реального кабинета продавца. У Ozon нет
публичной песочницы, поэтому это единственный способ прогнать полный путь
"запрос к Ozon -> товары в базе -> категории/поиск на фронте" без реальных
ключей.

Реализует эндпоинты, которые использует ozon_client.py:
  POST /v3/product/list              — список товаров (с пагинацией по last_id)
  POST /v3/product/info/list         — названия и description_category_id
  POST /v5/product/info/prices       — цены
  POST /v1/product/import/prices     — применение новой цены (approve в PricingDashboard)
  POST /v1/description-category/tree — дерево категорий (id -> имя)

Запуск:
    python scripts/mock_ozon_api.py            # слушает 127.0.0.1:5900

Дальше запускать AutoSync с окружением, направленным на этот мок:
    export OZON_SELLER_API_BASE=http://127.0.0.1:5900
    export OZON_CLIENT_ID=test
    export OZON_API_KEY=test
    python backend/native_app.py

Требует только Client-Id/Api-Key непустыми — конкретные значения не
проверяются, это не реальная авторизация.
"""

from __future__ import annotations

from flask import Flask, jsonify, request

app = Flask(__name__)

# Реальный Ozon отдаёт description_category_id (числовой) в /v3/product/info/list
# и имя категории — только отдельным деревом (/v1/description-category/tree),
# см. app/services/catalog_sync.py: _fetch_category_names(). Здесь дерево
# двухуровневое (родитель -> дети), как у настоящего Ozon, а не плоский список.
CATEGORY_TREE = [
    {
        "description_category_id": 90001,
        "category_name": "Автозапчасти",
        "children": [
            {"description_category_id": 90011, "category_name": "Тормозная система", "children": []},
            {"description_category_id": 90012, "category_name": "Двигатель", "children": []},
            {"description_category_id": 90013, "category_name": "Подвеска", "children": []},
        ],
    },
]

PRODUCTS = [
    {"product_id": 1001, "offer_id": "BRK-100", "name": "Тормозной диск передний Bosch", "description_category_id": 90011, "price": "3200.00"},
    {"product_id": 1002, "offer_id": "BRK-101", "name": "Тормозная колодка задняя TRW", "description_category_id": 90011, "price": "1450.00"},
    {"product_id": 1003, "offer_id": "ENG-200", "name": "Масляный фильтр Mann", "description_category_id": 90012, "price": "550.00"},
    {"product_id": 1004, "offer_id": "ENG-201", "name": "Свеча зажигания NGK", "description_category_id": 90012, "price": "320.00"},
    {"product_id": 1005, "offer_id": "ENG-202", "name": "Ремень ГРМ Gates", "description_category_id": 90012, "price": "1980.00"},
    {"product_id": 1006, "offer_id": "SUS-300", "name": "Амортизатор передний KYB", "description_category_id": 90013, "price": "4100.00"},
    {"product_id": 1007, "offer_id": "SUS-301", "name": "Стойка стабилизатора Lemforder", "description_category_id": 90013, "price": "890.00"},
    {"product_id": 1008, "offer_id": "MISC-1", "name": "Незамерзайка зимняя -30", "description_category_id": None, "price": "280.00"},
]


@app.before_request
def _check_auth():
    if not request.headers.get("Client-Id") or not request.headers.get("Api-Key"):
        return jsonify(message="Client-Id/Api-Key headers required"), 401


@app.post("/v3/product/list")
def product_list():
    body = request.get_json(force=True) or {}
    last_id = body.get("last_id") or ""
    limit = int(body.get("limit") or 100)
    offset = int(last_id) if last_id.isdigit() else 0

    page = PRODUCTS[offset : offset + limit]
    next_offset = offset + len(page)
    next_last_id = str(next_offset) if next_offset < len(PRODUCTS) else ""

    return jsonify(
        result={
            "items": [{"product_id": p["product_id"], "offer_id": p["offer_id"]} for p in page],
            "last_id": next_last_id,
            "total": len(PRODUCTS),
        }
    )


@app.post("/v3/product/info/list")
def product_info_list():
    body = request.get_json(force=True) or {}
    wanted = {int(pid) for pid in body.get("product_id", [])}
    items = [
        {
            "product_id": p["product_id"],
            "name": p["name"],
            "description_category_id": p["description_category_id"],
        }
        for p in PRODUCTS
        if p["product_id"] in wanted
    ]
    return jsonify(result={"items": items})


@app.post("/v1/description-category/tree")
def description_category_tree():
    return jsonify(result=CATEGORY_TREE)


@app.post("/v5/product/info/prices")
def product_info_prices():
    # v4 (тот же путь у настоящего Ozon) отдаёт 404 — снят с поддержки,
    # см. app/services/ozon_client.py: get_product_prices(). v5 отдаёт items
    # БЕЗ обёртки в "result" (в отличие от остальных эндпоинтов этого мока) —
    # воспроизводим это же несоответствие, иначе тесты не поймали бы регресс.
    body = request.get_json(force=True) or {}
    wanted = set(body.get("filter", {}).get("offer_id", []))
    items = [
        {"offer_id": p["offer_id"], "price": {"price": p["price"]}}
        for p in PRODUCTS
        if not wanted or p["offer_id"] in wanted
    ]
    return jsonify(items=items)


@app.post("/v1/product/import/prices")
def import_prices():
    """Применение цены после approve в PricingDashboard — реально меняет
    цену у товара в этом моке, чтобы следующая синхронизация/просмотр
    цены на фронте показывали уже новое значение (как было бы в реальном
    Ozon)."""
    body = request.get_json(force=True) or {}
    by_offer = {p["offer_id"]: p for p in PRODUCTS}
    results = []
    for update in body.get("prices", []):
        offer_id = update.get("offer_id")
        product = by_offer.get(offer_id)
        if product is None:
            results.append({"offer_id": offer_id, "updated": False, "errors": ["товар не найден"]})
            continue
        product["price"] = str(update.get("price"))
        results.append({"product_id": product["product_id"], "offer_id": offer_id, "updated": True, "errors": []})
    return jsonify(result=results)


if __name__ == "__main__":
    print("Мок Ozon Seller API: http://127.0.0.1:5900 (Ctrl+C для остановки)")
    app.run(host="127.0.0.1", port=5900)
