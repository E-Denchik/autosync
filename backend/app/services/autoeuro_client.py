"""Клиент API поставщика запчастей АвтоЕвро (REST v2, api.autoeuro.ru) —
цены, наличие и кросс-номера (аналоги) по бренду+артикулу.

Протокол подтверждён по официальной документации
(https://api.autoeuro.ru/doc/v2) и живыми тестовыми запросами с реальными
ключами заказчика (get_deliveries, get_balance — оба отвечают реальными
данными). Авторизация — единый API-ключ (логин/номер аккаунта заказчика в
запросах не участвуют, они только для входа в личный кабинет).

search_items требует ОБЕ пары brand+code — если бренд неизвестен (типовой
случай при сопоставлении заказ-наряда, где в документе есть только
артикул), сначала уточняем бренд через search_brands.
"""

from __future__ import annotations

import requests

BASE_URL = "https://api.autoeuro.ru/api/v2/json"


class AutoEuroError(RuntimeError):
    pass


class AutoEuroClient:
    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self._delivery_key_cache: str | None = None

    def _call(self, action: str, **params) -> list:
        if not self.api_key:
            raise AutoEuroError("AUTOEURO_API_KEY не задан")
        try:
            resp = requests.get(
                f"{BASE_URL}/{action}/{self.api_key}/",
                params={k: v for k, v in params.items() if v is not None},
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise AutoEuroError(f"АвтоЕвро недоступен: {exc}") from exc
        if not resp.ok:
            raise AutoEuroError(f"АвтоЕвро -> {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        meta = body.get("META", {})
        if "ERROR" in body:
            raise AutoEuroError(body["ERROR"].get("message") or "АвтоЕвро: неизвестная ошибка")
        if meta.get("client_state") and meta["client_state"] != "OK":
            raise AutoEuroError(meta["client_state"])
        return body.get("DATA", [])

    def get_balance(self) -> dict:
        data = self._call("get_balance")
        return data[0] if data else {}

    def get_deliveries(self) -> list[dict]:
        return self._call("get_deliveries")

    def _default_delivery_key(self) -> str:
        if self._delivery_key_cache is None:
            deliveries = self.get_deliveries()
            if not deliveries:
                raise AutoEuroError("АвтоЕвро: нет доступных способов получения (get_deliveries пуст)")
            self._delivery_key_cache = deliveries[0]["delivery_key"]
        return self._delivery_key_cache

    def search_brands(self, code: str) -> list[dict]:
        return self._call("search_brands", code=code)

    def search_items(self, brand: str, code: str, delivery_key: str | None = None, with_crosses: bool = True) -> list[dict]:
        return self._call(
            "search_items",
            brand=brand,
            code=code,
            delivery_key=delivery_key or self._default_delivery_key(),
            with_crosses=1 if with_crosses else 0,
        )

    def find_cross_references(self, article: str) -> list[dict]:
        """Кросс-номера (аналоги) для артикула — по контракту, которого ждёт
        matcher.py: список {"article": ..., "name": ..., "brand": ..., "price": ...}.

        Бренд неизвестен — уточняем через search_brands и опрашиваем найденные
        варианты по очереди, пока не наберём результат (обычно первого хватает)."""
        try:
            brands = self.search_brands(article)
        except AutoEuroError:
            return []

        refs = []
        for candidate in brands[:3]:
            try:
                items = self.search_items(candidate["brand"], candidate.get("code") or article)
            except AutoEuroError:
                continue
            for item in items:
                if item.get("cross") is None:
                    continue  # искомый товар сам по себе, не аналог
                refs.append(
                    {
                        "article": item.get("code"),
                        "brand": item.get("brand"),
                        "name": item.get("name"),
                        "price": item.get("price"),
                    }
                )
            if refs:
                break
        return refs

    def test_connection(self) -> str:
        balance = self.get_balance()
        active = "активен" if balance.get("active") else "НЕАКТИВЕН — обратитесь к менеджеру АвтоЕвро"
        return f"Подключение работает. Баланс: {balance.get('balance')} ₽, аккаунт {active}"
