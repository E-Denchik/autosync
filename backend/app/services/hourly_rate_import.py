"""Массовая загрузка ставок за нормо-час по маркам ТС из файла — общая
логика для ContractHourlyRate и ContragentHourlyRate (обе модели устроены
одинаково: внешний ключ + vehicle_make + hourly_rate), см.
app/api/contracts.py и app/api/contragents.py."""

from __future__ import annotations

from app.extensions import db
from app.services.document_parser import DocumentParseError, parse_hourly_rate_table


def import_hourly_rates(model_cls, fk_field: str, fk_value: int, file_path: str) -> dict:
    """Марка, уже заведённая для этого договора/контрагента, ОБНОВЛЯЕТСЯ
    (новая ставка вместо старой), а не дублируется — тот же принцип, что и
    при повторном импорте каталога договора (см. contract_catalog_import.py:
    заказчик может перезалить обновлённый файл ставок, не заводя вручную
    дубликаты по каждой марке). Сравнение марки регистронезависимое — см.
    репроцессинг заказ-наряда, где "Hyundai"/"HYUNDAI" должны быть одной
    и той же ставкой."""
    rows = parse_hourly_rate_table(file_path)
    if not rows:
        raise DocumentParseError("В файле не найдено ни одной строки со ставкой")

    existing = {
        r.vehicle_make.strip().lower(): r for r in model_cls.query.filter_by(**{fk_field: fk_value}).all()
    }

    created = 0
    updated = 0
    for row in rows:
        key = row["vehicle_make"].strip().lower()
        existing_row = existing.get(key)
        if existing_row is not None:
            existing_row.hourly_rate = row["hourly_rate"]
            updated += 1
        else:
            new_row = model_cls(**{fk_field: fk_value}, vehicle_make=row["vehicle_make"], hourly_rate=row["hourly_rate"])
            db.session.add(new_row)
            existing[key] = new_row
            created += 1

    db.session.commit()
    return {"created": created, "updated": updated, "total": len(rows)}
