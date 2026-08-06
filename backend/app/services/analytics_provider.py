"""Обёртка над сторонним аналитическим сервисом по Ozon (конкуренты).

ОТКРЫТЫЙ ВОПРОС (см. PROJECT.md/ARCHITECTURE.md): какой именно сервис
подключаем — MPSTATS, Moneyplace или аналог — нужно уточнить с заказчиком.
Публичные API этих сервисов похожи по форме (REST, API-key в заголовке),
поэтому интерфейс ниже написан как тонкая обёртка, которую нужно будет
донастроить под конкретные пути/поля выбранного провайдера.

Мы намеренно НЕ скрейпим Ozon напрямую — это архитектурное решение,
см. ozon_client.py.
"""

from __future__ import annotations

import requests


class AnalyticsProviderError(RuntimeError):
    pass


class AnalyticsProvider:
    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        if not base_url:
            raise AnalyticsProviderError(
                "ANALYTICS_PROVIDER_BASE_URL не задан — провайдер ещё не выбран заказчиком"
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def get_competitor_prices(self, sku_or_query: str, category: str | None = None) -> dict:
        """Возвращает цены/позиции конкурентов по запросу/категории.

        TODO: заменить путь и разбор ответа на схему выбранного провайдера,
        когда он будет согласован с заказчиком. Форма ответа ниже —
        нормализованный контракт, которого должен придерживаться остальной
        backend (используется в tasks/sync_ozon_prices.py).
        """
        try:
            resp = requests.get(
                f"{self.base_url}/v1/competitors",
                params={"query": sku_or_query, "category": category},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise AnalyticsProviderError(f"analytics provider недоступен: {exc}") from exc
        if not resp.ok:
            raise AnalyticsProviderError(f"analytics provider -> {resp.status_code}: {resp.text}")
        data = resp.json()
        return {
            "min_price": data.get("min_price"),
            "avg_price": data.get("avg_price"),
            "max_price": data.get("max_price"),
            "sample_size": data.get("sample_size"),
            "raw": data,
        }

    def test_connection(self) -> str:
        """Лёгкая проверка доступности провайдера тестовым запросом.

        Ожидаемо падает с AnalyticsProviderError, пока реальный провайдер
        не выбран/не настроен заказчиком — это нормальный результат теста,
        а не баг.
        """
        result = self.get_competitor_prices("тест")
        return f"Подключение работает, образец ответа: min={result.get('min_price')}, avg={result.get('avg_price')}"
