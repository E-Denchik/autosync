"""Поиск по внутренней номенклатуре/складу заказчика (код, № кат.,
производитель, остаток, резерв, в производстве, склад) — источник 1С:Альфа-Авто.

Как и AutoDataClient для нормо-часов, этот клиент работает в двух режимах:
  - ALFAAUTO_BASE_URL не задан (по умолчанию) — ищем по локальной таблице
    NomenclatureEntry, которую наполняют через nomenclature_import.py
    (загрузка файла) или вручную из UI.
  - Задан — обращаемся к реальному OData.
"""

from __future__ import annotations

import difflib

import requests

from app.extensions import db
from app.models import NomenclatureEntry

FUZZY_NAME_THRESHOLD = 0.6  # ниже — считаем, что совпадения по названию нет


class NomenclatureClientError(RuntimeError):
    pass


class NomenclatureClient:
    def __init__(self, base_url: str, login: str = "", password: str = "", timeout: int = 15):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.login = login
        self.password = password
        self.timeout = timeout

    def _auth(self) -> tuple[str, str] | None:
        return (self.login, self.password) if self.login else None

    def discover_entities(self) -> list[str]:
        try:
            resp = requests.get(
                f"{self.base_url}/",
                params={"$format": "json"},
                headers={"Accept": "application/json"},
                auth=self._auth(),
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise NomenclatureClientError(f"1С OData недоступен: {exc}") from exc
        if not resp.ok:
            raise NomenclatureClientError(f"1С OData -> {resp.status_code}: {resp.text}")
        return [entry["name"] for entry in resp.json().get("value", [])]

    def find_match(self, code: str | None, name: str | None) -> dict | None:
        """Возвращает лучшую запись номенклатуры для артикула/названия
        сопоставленной запчасти, либо None, если ничего не найдено.

        Формат возврата (нормализованный контракт, ждёт nomenclature_matcher.py):
            {"code", "cat_number", "manufacturer", "name", "unit", "stock_qty",
             "reserved_qty", "in_production_qty", "ordered_qty", "warehouse",
             "match_source": "code" | "fuzzy_name"}
        """
        if self.base_url:
            return self._find_remote(code, name)
        return self._find_local(code, name)

    def _find_remote(self, code: str | None, name: str | None) -> dict | None:
        try:
            resp = requests.get(
                f"{self.base_url}/Catalog_Номенклатура",
                params={"$filter": f"Код eq '{code or name or ''}'", "$format": "json"},
                headers={"Accept": "application/json"},
                auth=self._auth(),
                timeout=self.timeout,
            )
        except requests.exceptions.RequestException as exc:
            raise NomenclatureClientError(f"1С OData недоступен: {exc}") from exc
        if not resp.ok:
            raise NomenclatureClientError(f"1С OData -> {resp.status_code}: {resp.text}")
        results = resp.json().get("value") or []
        return results[0] if results else None

    def _find_local(self, code: str | None, name: str | None) -> dict | None:
        entry = None
        match_source = None

        if code:
            entry = (
                NomenclatureEntry.query.filter(
                    db.or_(NomenclatureEntry.code == code, NomenclatureEntry.cat_number == code)
                )
                .first()
            )
            if entry:
                match_source = "code"

        if entry is None and name:
            entry, score = self._best_fuzzy_match(name)
            if entry is not None and score >= FUZZY_NAME_THRESHOLD:
                match_source = "fuzzy_name"
            else:
                entry = None

        if entry is None:
            return None

        return {
            "code": entry.code,
            "cat_number": entry.cat_number,
            "manufacturer": entry.manufacturer,
            "name": entry.name,
            "unit": entry.unit,
            "stock_qty": float(entry.stock_qty) if entry.stock_qty is not None else None,
            "reserved_qty": float(entry.reserved_qty) if entry.reserved_qty is not None else None,
            "in_production_qty": float(entry.in_production_qty) if entry.in_production_qty is not None else None,
            "ordered_qty": float(entry.ordered_qty) if entry.ordered_qty is not None else None,
            "warehouse": entry.warehouse,
            "match_source": match_source,
        }

    @staticmethod
    def _best_fuzzy_match(name: str) -> tuple[NomenclatureEntry | None, float]:
        """Простое нечёткое совпадение по названию средствами stdlib
        (difflib) — без похода в LLM: это вспомогательное обогащение, а не
        решающий шаг сопоставления, для которого matcher.py уже бережёт
        LLM только на крайний случай (см. ARCHITECTURE.md)."""
        normalized = name.strip().lower()
        best_entry, best_score = None, 0.0
        for entry in NomenclatureEntry.query.all():
            score = difflib.SequenceMatcher(None, normalized, entry.name.strip().lower()).ratio()
            if score > best_score:
                best_entry, best_score = entry, score
        return best_entry, best_score

    def test_connection(self) -> str:
        if not self.base_url:
            count = NomenclatureEntry.query.count()
            return f"Работает по локальной таблице номенклатуры ({count} записей) — 1С не подключена"
        entities = self.discover_entities()
        return f"1С OData отвечает, опубликовано объектов: {len(entities)} (например: {', '.join(entities[:5])})"
