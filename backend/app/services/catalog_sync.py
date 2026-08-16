"""Синхронизация каталога товаров с Ozon Seller API — создаёт/обновляет
Product-записи на основе того, что реально числится в кабинете продавца.

Ручное добавление товаров через UI закрыто намеренно (см. PROJECT.md,
"Открытые вопросы" / решение заказчика) — единственный источник товаров это
Ozon. Без этого job'а каталог остаётся пустым, пока не заданы
OZON_CLIENT_ID/OZON_API_KEY (см. Администрирование → Интеграции).

Вызывается из APScheduler в native_app.py по расписанию и вручную через
POST /api/ozon/cards/sync. Требование: выполнять внутри app_context().
"""

from __future__ import annotations

from flask import current_app

from app.extensions import db
from app.models import Product
from app.services.history import log_change
from app.services.ozon_client import OzonClient, OzonClientError, extract_items

PAGE_SIZE = 100
MAX_PAGES = 1000  # защита от бесконечного цикла, если Ozon вернёт "зависший" last_id


def _extract_category_nodes(tree_resp: dict) -> list[dict]:
    result = tree_resp.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "items" in result:
        return result["items"]
    return tree_resp.get("items", [])


def _flatten_category_names(nodes: list[dict], out: dict[int, str]) -> None:
    """Дерево категорий Ozon вложенное (children) — сплющиваем в плоскую
    карту id -> имя, нам нужны только листовые/промежуточные названия для
    отображения, не сама иерархия."""
    for node in nodes:
        category_id = node.get("description_category_id")
        name = node.get("category_name")
        if category_id is not None and name:
            try:
                out[int(category_id)] = name
            except (TypeError, ValueError):
                pass
        children = node.get("children") or []
        if children:
            _flatten_category_names(children, out)


def _fetch_category_names(ozon: OzonClient) -> dict[int, str]:
    names: dict[int, str] = {}
    try:
        tree_resp = ozon.get_category_tree()
    except OzonClientError as exc:
        current_app.logger.warning("Ozon catalog sync: не удалось получить дерево категорий: %s", exc)
        return names
    _flatten_category_names(_extract_category_nodes(tree_resp), names)
    return names


def sync_ozon_catalog_job() -> dict:
    ozon = OzonClient(
        current_app.config["OZON_CLIENT_ID"],
        current_app.config["OZON_API_KEY"],
    )

    created = 0
    updated = 0
    last_id = ""

    # Один раз на весь синк, не на страницу — дерево категорий не зависит
    # от товаров и не меняется между страницами одного прогона.
    category_names = _fetch_category_names(ozon)

    for _ in range(MAX_PAGES):
        try:
            page = ozon.list_products(last_id=last_id, limit=PAGE_SIZE)
        except OzonClientError as exc:
            current_app.logger.error("Ozon catalog sync: %s", exc)
            if created == 0 and updated == 0:
                return {"status": "failed", "error": str(exc)}
            break  # частичный успех — то, что успели забрать, уже сохранено

        items = extract_items(page)
        if not items:
            break

        product_ids = [str(item["product_id"]) for item in items if item.get("product_id")]
        offer_ids = [item["offer_id"] for item in items if item.get("offer_id")]

        info_by_id: dict[str, dict] = {}
        try:
            info_resp = ozon.get_product_info(product_ids)
            for info in extract_items(info_resp):
                pid = str(info.get("product_id") or info.get("id") or "")
                if pid:
                    info_by_id[pid] = info
        except OzonClientError as exc:
            current_app.logger.warning("Ozon catalog sync: не удалось получить названия товаров: %s", exc)

        price_by_offer: dict[str, str] = {}
        try:
            prices_resp = ozon.get_product_prices(offer_ids=offer_ids)
            # v5 отдаёт items без обёртки в "result" (в отличие от list_products
            # /product_info) — extract_items уже поддерживает оба варианта.
            for p in extract_items(prices_resp):
                price_by_offer[p.get("offer_id")] = p.get("price", {}).get("price")
        except OzonClientError as exc:
            current_app.logger.warning("Ozon catalog sync: не удалось получить цены: %s", exc)

        for item in items:
            ozon_product_id = str(item.get("product_id") or "")
            offer_id = item.get("offer_id")
            if not ozon_product_id or not offer_id:
                continue
            ozon_sku = str(item.get("sku") or "") or None

            info = info_by_id.get(ozon_product_id, {})
            name = info.get("name") or offer_id
            # description_category_id — числовой, резолвим через дерево
            # категорий (category_names, см. _fetch_category_names). Фолбэк
            # на готовое имя (category/category_name) — на случай, если
            # какая-то версия ответа отдаёт его напрямую, либо id не нашёлся
            # в дереве (например категория отключена в Ozon).
            category_id = info.get("description_category_id")
            category = None
            if category_id not in (None, ""):
                try:
                    category = category_names.get(int(category_id))
                except (TypeError, ValueError):
                    category = None
            category = category or info.get("category") or info.get("category_name")
            price_raw = price_by_offer.get(offer_id)
            try:
                price_val = float(price_raw) if price_raw not in (None, "") else None
            except (TypeError, ValueError):
                current_app.logger.warning("Ozon catalog sync: не удалось разобрать цену %r для %s", price_raw, offer_id)
                price_val = None

            product = Product.query.filter_by(ozon_product_id=ozon_product_id).first()
            if product is None:
                product = Product(
                    ozon_product_id=ozon_product_id,
                    sku=offer_id,
                    ozon_sku=ozon_sku,
                    name=name,
                    category=category,
                    current_price=price_val,
                )
                db.session.add(product)
                db.session.flush()
                log_change("product", product.id, "created", details={"source": "ozon_sync"})
                created += 1
            else:
                changed = False
                if product.sku != offer_id:
                    product.sku = offer_id
                    changed = True
                if ozon_sku and product.ozon_sku != ozon_sku:
                    product.ozon_sku = ozon_sku
                    changed = True
                if info.get("name") and product.name != info["name"]:
                    product.name = info["name"]
                    changed = True
                if category and product.category != category:
                    product.category = category
                    changed = True
                current_val = float(product.current_price) if product.current_price is not None else None
                if price_val is not None and current_val != price_val:
                    product.current_price = price_val
                    changed = True
                if changed:
                    log_change("product", product.id, "edited", details={"source": "ozon_sync"})
                    updated += 1

        next_last_id = (page.get("result") or {}).get("last_id") or page.get("last_id") or ""
        if not next_last_id or next_last_id == last_id:
            break
        last_id = next_last_id
    else:
        current_app.logger.warning("Ozon catalog sync: остановлено по лимиту в %s страниц", MAX_PAGES)

    db.session.commit()
    return {"status": "ok", "created": created, "updated": updated}
