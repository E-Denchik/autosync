"""Обёртка над Ozon Seller API / Performance API.

Только официальные, документированные эндпоинты — своих товаров, цен,
продаж и позиций. Прямой скрейпинг страниц Ozon здесь запрещён архитектурно
(см. ARCHITECTURE.md, PROJECT.md): ToS нарушается, аккаунт можно забанить.
Если нужны данные, которых нет в Seller/Performance API — это разговор
с продактом, а не инженерное решение в этом файле.
"""

from __future__ import annotations

import requests

SELLER_API_BASE = "https://api-seller.ozon.ru"
PERFORMANCE_API_BASE = "https://performance.ozon.ru"


class OzonClientError(RuntimeError):
    pass


class OzonClient:
    def __init__(self, client_id: str, api_key: str, timeout: int = 30):
        self.client_id = client_id
        self.api_key = api_key
        self.timeout = timeout

    def _seller_headers(self) -> dict:
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict | None = None) -> dict:
        resp = requests.post(
            f"{SELLER_API_BASE}{path}",
            json=payload or {},
            headers=self._seller_headers(),
            timeout=self.timeout,
        )
        if not resp.ok:
            raise OzonClientError(f"Ozon Seller API {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def list_products(self, last_id: str = "", limit: int = 100) -> dict:
        """GET-аналог /v3/product/list — список товаров продавца."""
        return self._post(
            "/v3/product/list",
            {"filter": {}, "last_id": last_id, "limit": limit},
        )

    def get_product_prices(self, offer_ids: list[str] | None = None) -> dict:
        """/v4/product/info/prices — текущие цены своих товаров."""
        filt = {"offer_id": offer_ids} if offer_ids else {}
        return self._post("/v4/product/info/prices", {"filter": filt, "limit": 1000})

    def update_prices(self, price_updates: list[dict]) -> dict:
        """/v1/product/import/prices — применение новой цены.

        ВАЖНО: вызывается только после явного approve человеком на фронте
        (PricingDashboard). Автоприменение цен отключено намеренно.
        """
        return self._post("/v1/product/import/prices", {"prices": price_updates})

    def get_sales_stats(self, date_from: str, date_to: str) -> dict:
        """/v1/analytics/data — свои продажи/позиции в выдаче за период."""
        return self._post(
            "/v1/analytics/data",
            {
                "date_from": date_from,
                "date_to": date_to,
                "metrics": ["ordered_units", "revenue", "position_category"],
                "dimension": ["sku"],
            },
        )
