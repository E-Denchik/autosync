"""Массовая загрузка справочника нормо-часов (операция + норма часов по
маркам/моделям ТС, см. app/models/labor_catalog.py и api/labor_catalog.py) —
раньше пополнялся только вручную по одной записи (см. LaborCatalog.jsx),
хотя ставки по маркам контрагента/договора уже давно грузятся файлом (см.
hourly_rate_import.py, тот же принцип upsert здесь)."""

from __future__ import annotations

from app.extensions import db
from app.models import LaborCatalogEntry
from app.services.document_parser import DocumentParseError, parse_labor_catalog_table


def _key(vehicle_make: str, vehicle_model: str | None, operation_name: str) -> tuple[str, str | None, str]:
    return (
        vehicle_make.strip().lower(),
        (vehicle_model or "").strip().lower() or None,
        operation_name.strip().lower(),
    )


def import_labor_catalog(file_path: str, llm_client=None) -> dict:
    """Та же операция для той же марки+модели, уже заведённая в справочнике —
    ОБНОВЛЯЕТСЯ (новая норма вместо старой), а не дублируется. Марка без
    модели — отдельная запись "на все модели этой марки", как и у ставок.

    llm_client — только для сканов/фото (см. parse_labor_catalog_table)."""
    rows = parse_labor_catalog_table(file_path, llm_client=llm_client)
    if not rows:
        raise DocumentParseError("В файле не найдено ни одной строки с нормо-часами")

    existing = {_key(e.vehicle_make, e.vehicle_model, e.operation_name): e for e in LaborCatalogEntry.query.all()}

    created = 0
    updated = 0
    for row in rows:
        key = _key(row["vehicle_make"], row.get("vehicle_model"), row["operation_name"])
        existing_row = existing.get(key)
        if existing_row is not None:
            existing_row.norm_hours = row["norm_hours"]
            existing_row.source = "import"
            updated += 1
        else:
            new_row = LaborCatalogEntry(
                vehicle_make=row["vehicle_make"],
                vehicle_model=row.get("vehicle_model"),
                operation_name=row["operation_name"],
                norm_hours=row["norm_hours"],
                source="import",
            )
            db.session.add(new_row)
            existing[key] = new_row
            created += 1

    db.session.commit()
    return {"created": created, "updated": updated, "total": len(rows)}
