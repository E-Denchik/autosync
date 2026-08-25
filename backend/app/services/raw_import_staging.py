"""Промежуточное хранение сырых строк, разобранных из загруженного файла
(каталог договора или заказ-наряд), ДО того, как они станут ContractPart/
PartMatch/LaborLine — см. app/models/raw_import_row.py про то, почему
JSON-поле в обычной таблице, а не динамическая схема на файл.

Поток для обеих сторон (см. contract_catalog_import.py,
repair_order_processor.py) один и тот же:
    распарсили файл -> stage_raw_rows() -> (тут же, до/во время "иишка
    проверяет и адаптирует", напр. brand_normalizer.py) -> строки идут в
    постоянные таблицы -> mark_rows_moved().
"""

from __future__ import annotations

from app.extensions import db
from app.models import RawImportRow

BATCH_SIZE = 2000


def stage_raw_rows(
    rows: list[dict],
    *,
    row_kind: str,
    contract_id: int | None = None,
    repair_order_id: int | None = None,
    source_filename: str | None = None,
) -> None:
    """Сохраняет rows как есть (произвольный набор полей на строку — JSON
    не требует одинаковой формы у всех строк) со status="staged". Не
    коммитит — вызывающий код сам решает, когда сохранить транзакцию."""
    if not rows:
        return
    mappings = [
        {
            "contract_id": contract_id,
            "repair_order_id": repair_order_id,
            "row_kind": row_kind,
            "source_filename": source_filename,
            "row_index": i,
            "raw_data": row,
            "status": "staged",
        }
        for i, row in enumerate(rows)
    ]
    for i in range(0, len(mappings), BATCH_SIZE):
        db.session.bulk_insert_mappings(RawImportRow, mappings[i : i + BATCH_SIZE])


def mark_rows_moved(*, contract_id: int | None = None, repair_order_id: int | None = None, row_kind: str | None = None) -> None:
    """Помечает застейдженные строки перенесёнными в постоянные таблицы —
    вызывается после того, как они реально там оказались (см.
    _bulk_insert_parts в contract_catalog_import.py, создание PartMatch/
    LaborLine в repair_order_processor.py)."""
    query = RawImportRow.query.filter_by(status="staged")
    if contract_id is not None:
        query = query.filter_by(contract_id=contract_id)
    if repair_order_id is not None:
        query = query.filter_by(repair_order_id=repair_order_id)
    if row_kind is not None:
        query = query.filter_by(row_kind=row_kind)
    query.update({"status": "moved"}, synchronize_session=False)
