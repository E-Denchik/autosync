from __future__ import annotations

import requests

from app.extensions import db
from app.models import LaborCatalogEntry


class AutoDataError(RuntimeError):
    pass


class AutoDataClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 15):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def find_norm_hours(self, vehicle_make: str, vehicle_model: str | None) -> list[dict]:
        if self.base_url:
            resp = requests.get(
                f"{self.base_url}/v1/norm-hours",
                params={"make": vehicle_make, "model": vehicle_model or ""},
                headers=self._headers(),
                timeout=self.timeout,
            )
            if not resp.ok:
                raise AutoDataError(f"AutoData -> {resp.status_code}: {resp.text}")
            return resp.json().get("results", [])
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
