"""Обёртка над Ozon Seller API / Performance API.

Только официальные, документированные эндпоинты — своих товаров, цен,
продаж и позиций. Прямой скрейпинг страниц Ozon здесь запрещён архитектурно
(см. ARCHITECTURE.md, PROJECT.md): ToS нарушается, аккаунт можно забанить.
Если нужны данные, которых нет в Seller/Performance API — это разговор
с продактом, а не инженерное решение в этом файле.

Seller и Performance — два разных API с разной авторизацией (статичные
заголовки Client-Id/Api-Key против OAuth2 client_credentials), у Ozon это
исторически разные продукты. Держим оба в одном классе, т.к. с точки
зрения бизнеса это один и тот же кабинет продавца.
"""

from __future__ import annotations

import os

import requests

DEFAULT_SELLER_API_BASE = "https://api-seller.ozon.ru"
DEFAULT_PERFORMANCE_API_BASE = "https://performance.ozon.ru"

# Переопределяемо через env — нужно, чтобы направить клиент на локальный
# мок-сервер для тестирования без реального кабинета Ozon (см.
# scripts/mock_ozon_api.py). В проде/по умолчанию — настоящие адреса Ozon.
# ВАЖНО: если эта переменная задана в терминале (например, осталась от
# тестирования с моком) — реальные ключи, введённые в UI, работать не
# будут, пока её не убрать (unset). См. app/api/integrations.py:
# api_base_override — предупреждение об этом в UI.
SELLER_API_BASE = os.environ.get("OZON_SELLER_API_BASE", DEFAULT_SELLER_API_BASE)
PERFORMANCE_API_BASE = os.environ.get("OZON_PERFORMANCE_API_BASE", DEFAULT_PERFORMANCE_API_BASE)


class OzonClientError(RuntimeError):
    pass


class OzonClient:
    def __init__(
        self,
        client_id: str = "",
        api_key: str = "",
        performance_client_id: str | None = None,
        performance_client_secret: str | None = None,
        timeout: int = 30,
    ):
        self.client_id = client_id
        self.api_key = api_key
        self.performance_client_id = performance_client_id
        self.performance_client_secret = performance_client_secret
        self.timeout = timeout
        self._performance_token: str | None = None

    # ---------- Seller API (Client-Id/Api-Key в заголовках) ----------

    def _seller_headers(self) -> dict:
        if not self.client_id or not self.api_key:
            raise OzonClientError(
                "OZON_CLIENT_ID и OZON_API_KEY не заданы — Seller API не подключён"
            )
        return {
            "Client-Id": self.client_id,
            "Api-Key": self.api_key,
            "Content-Type": "application/json",
        }

    def _post(self, path: str, payload: dict | None = None) -> dict:
        headers = self._seller_headers()
        try:
            resp = requests.post(
                f"{SELLER_API_BASE}{path}",
                json=payload or {},
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise OzonClientError(f"Ozon Seller API {path} недоступен: {exc}") from exc
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

    def get_product_info(self, product_ids: list[str]) -> dict:
        """/v3/product/info/list — название и категория товаров по product_id
        (list_products отдаёт только id/offer_id, без названия).

        НЕ проверено вживую без реальных ключей — сопоставление полей ответа
        (name/category) сделано по документации Ozon Seller API и может
        потребовать корректировки, см. ARCHITECTURE.md, "Открытые вопросы".
        """
        return self._post("/v3/product/info/list", {"product_id": product_ids})

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

    def test_seller_connection(self) -> str:
        """Самый лёгкий реальный вызов Seller API — не тратит квоту на
        запись, только подтверждает, что Client-Id/Api-Key рабочие."""
        result = self.list_products(limit=1)
        total = result.get("result", {}).get("total", 0)
        return f"Подключение работает, товаров в кабинете: {total}"

    # ---------- Performance API (OAuth2 client_credentials) ----------

    def _performance_headers(self) -> dict:
        if not self.performance_client_id or not self.performance_client_secret:
            raise OzonClientError(
                "OZON_PERFORMANCE_CLIENT_ID и OZON_PERFORMANCE_CLIENT_SECRET не заданы"
                " — Performance API не подключён"
            )
        if not self._performance_token:
            try:
                resp = requests.post(
                    f"{PERFORMANCE_API_BASE}/api/client/token",
                    json={
                        "client_id": self.performance_client_id,
                        "client_secret": self.performance_client_secret,
                        "grant_type": "client_credentials",
                    },
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                raise OzonClientError(f"Ozon Performance API токен недоступен: {exc}") from exc
            if not resp.ok:
                raise OzonClientError(f"Ozon Performance API токен -> {resp.status_code}: {resp.text}")
            self._performance_token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {self._performance_token}", "Content-Type": "application/json"}

    def list_campaigns(self) -> dict:
        """GET /api/client/campaign — рекламные кампании. Не используется
        сейчас бизнес-логикой модулей (см. PROJECT.md) — просто самый
        лёгкий read-only вызов, чтобы подтвердить, что OAuth2-токен реально
        выдаётся и работает."""
        headers = self._performance_headers()
        try:
            resp = requests.get(
                f"{PERFORMANCE_API_BASE}/api/client/campaign",
                headers=headers,
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise OzonClientError(f"Ozon Performance API /campaign недоступен: {exc}") from exc
        if not resp.ok:
            raise OzonClientError(f"Ozon Performance API /campaign -> {resp.status_code}: {resp.text}")
        return resp.json()

    def test_performance_connection(self) -> str:
        result = self.list_campaigns()
        campaigns = result.get("list", [])
        return f"Подключение работает, кампаний: {len(campaigns)}"
