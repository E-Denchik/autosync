"""Обёртка над API поставщика запчастей (цены, наличие, кросс-номера).

ОТКРЫТЫЙ ВОПРОС (см. PROJECT.md/ARCHITECTURE.md): точная схема ответа API
поставщика — какие поля доступны для кросс-референсов — уточняется с
заказчиком (доступ уже есть, схема нет). Интерфейс ниже фиксирует
нормализованный контракт, которого ждёт matcher.py; реализацию запросов
нужно донастроить под реальный API, когда придёт документация.
"""

from __future__ import annotations

import requests


class PartsSupplierError(RuntimeError):
    pass


class PartsSupplierClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def find_by_article(self, article: str) -> dict | None:
        """Точный поиск по артикулу. Возвращает None, если не найдено."""
        if not self.base_url:
            raise PartsSupplierError("PARTS_SUPPLIER_BASE_URL не задан")
        resp = requests.get(
            f"{self.base_url}/v1/parts",
            params={"article": article},
            headers=self._headers(),
            timeout=self.timeout,
        )
        if resp.status_code == 404:
            return None
        if not resp.ok:
            raise PartsSupplierError(f"parts supplier -> {resp.status_code}: {resp.text}")
        return resp.json() or None

    def find_cross_references(self, article: str) -> list[dict]:
        """Кросс-номера/аналоги для артикула, которого нет напрямую у поставщика.

        TODO: подтвердить с заказчиком, какие поля реально отдаёт API
        (только цена/наличие, или ещё сами кросс-номера аналогов).
        """
        if not self.base_url:
            raise PartsSupplierError("PARTS_SUPPLIER_BASE_URL не задан")
        resp = requests.get(
            f"{self.base_url}/v1/parts/cross-references",
            params={"article": article},
            headers=self._headers(),
            timeout=self.timeout,
        )
        if not resp.ok:
            raise PartsSupplierError(f"parts supplier -> {resp.status_code}: {resp.text}")
        return resp.json().get("results", [])
