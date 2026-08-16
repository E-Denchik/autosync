from __future__ import annotations

import requests

from app.extensions import db
from app.models import LaborCatalogEntry


class AutoDataError(RuntimeError):
    pass


class AutoDataClient:
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
            raise AutoDataError(f"1С OData недоступен: {exc}") from exc
        if not resp.ok:
            raise AutoDataError(f"1С OData -> {resp.status_code}: {resp.text}")
        return [entry["name"] for entry in resp.json().get("value", [])]

    def find_norm_hours(self, vehicle_make: str, vehicle_model: str | None) -> list[dict]:
        if self.base_url:
            try:
                resp = requests.get(
                    f"{self.base_url}/Catalog_НормыВремени",
                    params={
                        "$filter": f"МаркаТС eq '{vehicle_make}'"
                        + (f" and (МодельТС eq '{vehicle_model}' or МодельТС eq null)" if vehicle_model else ""),
                        "$format": "json",
                    },
                    headers={"Accept": "application/json"},
                    auth=self._auth(),
                    timeout=self.timeout,
                )
            except requests.exceptions.RequestException as exc:
                raise AutoDataError(f"1С OData недоступен: {exc}") from exc
            if not resp.ok:
                raise AutoDataError(f"1С OData -> {resp.status_code}: {resp.text}")
            return resp.json().get("value", [])
        return self._find_local(vehicle_make, vehicle_model)

    def _find_local(self, vehicle_make: str, vehicle_model: str | None) -> list[dict]:
        query = LaborCatalogEntry.query.filter(
            db.func.lower(LaborCatalogEntry.vehicle_make) == (vehicle_make or "").lower()
        )
        if vehicle_model:
            query = query.filter(
                db.or_(
                    LaborCatalogEntry.vehicle_model.is_(None),
                    db.func.lower(LaborCatalogEntry.vehicle_model) == vehicle_model.lower(),
                )
            )
        return [
            {
                "operation_name": entry.operation_name,
                "norm_hours": float(entry.norm_hours),
                "vehicle_make": entry.vehicle_make,
                "vehicle_model": entry.vehicle_model,
            }
            for entry in query.all()
        ]

    def test_connection(self) -> str:
        if not self.base_url:
            count = LaborCatalogEntry.query.count()
            return f"Работает по локальному справочнику нормо-часов ({count} записей) — 1С не подключена"
        entities = self.discover_entities()
        return f"1С OData отвечает, опубликовано объектов: {len(entities)} (например: {', '.join(entities[:5])})"
