"""Обёртка над API поставщика запчастей (цены, наличие, кросс-номера).

Общий PARTS_SUPPLIER_BASE_URL/API_KEY ниже — placeholder под изначально
задуманный единый API поставщика, схема которого так и не пришла. Реальные
подключённые поставщики — Rossco/АвтоЕвро/Москворечье (см. rossco_client.py,
autoeuro_client.py, moskvorechye_client.py) — у каждого свой протокол и
свой клиент; AggregatedPartsSupplierClient ниже опрашивает все настроенные
разом и объединяет кросс-номера, поэтому matcher.py по-прежнему работает с
одним объектом с единственным методом find_cross_references(article).
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


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
        try:
            resp = requests.get(
                f"{self.base_url}/v1/parts",
                params={"article": article},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise PartsSupplierError(f"parts supplier недоступен: {exc}") from exc
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
        try:
            resp = requests.get(
                f"{self.base_url}/v1/parts/cross-references",
                params={"article": article},
                headers=self._headers(),
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise PartsSupplierError(f"parts supplier недоступен: {exc}") from exc
        if not resp.ok:
            raise PartsSupplierError(f"parts supplier -> {resp.status_code}: {resp.text}")
        return resp.json().get("results", [])


class AggregatedPartsSupplierClient:
    """Опрашивает разом все настроенные реальные API поставщиков запчастей
    (Rossco/АвтоЕвро/Москворечье + опциональный общий PARTS_SUPPLIER_*) и
    объединяет кросс-номера в один список — matcher.py ждёт единственный
    объект с find_cross_references(article), не по одному на поставщика.

    Отказ ОДНОГО поставщика (сеть, неверные ключи, лимиты) не должен
    останавливать сопоставление — тихо пропускаем и логируем, остальные
    поставщики (и LLM-фоллбэк следом) всё равно отработают."""

    def __init__(self, clients: list) -> None:
        self._clients = clients

    def find_cross_references(self, article: str) -> list[dict]:
        seen = set()
        merged: list[dict] = []
        for client in self._clients:
            try:
                refs = client.find_cross_references(article)
            except Exception as exc:
                logger.warning("%s.find_cross_references(%r) упал: %s", type(client).__name__, article, exc)
                continue
            for ref in refs:
                key = ref.get("article")
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(ref)
        return merged


def build_configured_supplier_client(cfg) -> AggregatedPartsSupplierClient:
    """Собирает AggregatedPartsSupplierClient из тех поставщиков, у которых
    в настройках реально есть ключи — остальные просто не участвуют в
    опросе (не шлём заведомо обречённые запросы)."""
    from app.services.autoeuro_client import AutoEuroClient
    from app.services.moskvorechye_client import MoskvorechyeClient
    from app.services.rossco_client import RosscoClient

    clients: list = []
    if cfg["PARTS_SUPPLIER_BASE_URL"]:
        clients.append(PartsSupplierClient(cfg["PARTS_SUPPLIER_BASE_URL"], cfg["PARTS_SUPPLIER_API_KEY"]))
    if cfg["ROSSCO_KEY1"] and cfg["ROSSCO_KEY2"]:
        clients.append(RosscoClient(cfg["ROSSCO_KEY1"], cfg["ROSSCO_KEY2"]))
    if cfg["AUTOEURO_API_KEY"]:
        clients.append(AutoEuroClient(cfg["AUTOEURO_API_KEY"]))
    if cfg["MOSKVORECHYE_BASE_URL"] and cfg["MOSKVORECHYE_API_KEY"]:
        clients.append(MoskvorechyeClient(cfg["MOSKVORECHYE_BASE_URL"], cfg["MOSKVORECHYE_API_KEY"]))
    return AggregatedPartsSupplierClient(clients)
