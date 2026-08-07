"""Импорт номенклатуры/остатков заказчика из файла (Excel/ODS/CSV) —
на случай, если это окажется периодическая выгрузка из 1С, а не живой
API (см. nomenclature_client.py — там же открытый вопрос про источник).

Формат неизвестен заранее (у каждого заказчика/учётной системы он свой),
поэтому колонки распознаются по RU-синонимам, как и в document_parser.py.
Строки без "наименования" и без кода/каталожного номера пропускаются —
такая строка ничего не добавляет к сопоставлению.
"""

from __future__ import annotations

import os

import pandas as pd

from app.extensions import db
from app.models import NomenclatureEntry

CODE_ALIASES = ["код товара", "код", "артикул"]
CAT_NUMBER_ALIASES = ["№ кат", "номер кат", "каталожный номер", "кат. номер", "cat number", "cat_number"]
MANUFACTURER_ALIASES = ["производитель", "бренд", "manufacturer"]
NAME_ALIASES = ["номенклатура", "наименование", "название", "name"]
UNIT_ALIASES = ["единица", "ед.", "unit"]
STOCK_ALIASES = ["остаток", "stock"]
ORDERED_ALIASES = ["заказано", "ordered"]
RESERVED_ALIASES = ["в резерве", "резерв", "reserved"]
IN_PRODUCTION_ALIASES = ["в производстве", "производств"]
WAREHOUSE_ALIASES = ["склад", "warehouse"]
PRICE_ALIASES = ["цена", "price"]


class NomenclatureImportError(RuntimeError):
    pass


def _match_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {c: str(c).strip().lower() for c in columns}
    for col, norm in normalized.items():
        if any(alias in norm for alias in aliases):
            return col
    return None


def _clean_str(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value).strip() or None


def _clean_num(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _dataframe_to_rows(df: pd.DataFrame) -> list[dict]:
    columns = list(df.columns)
    col = {
        "code": _match_column(columns, CODE_ALIASES),
        "cat_number": _match_column(columns, CAT_NUMBER_ALIASES),
        "manufacturer": _match_column(columns, MANUFACTURER_ALIASES),
        "name": _match_column(columns, NAME_ALIASES),
        "unit": _match_column(columns, UNIT_ALIASES),
        "stock_qty": _match_column(columns, STOCK_ALIASES),
        "ordered_qty": _match_column(columns, ORDERED_ALIASES),
        "reserved_qty": _match_column(columns, RESERVED_ALIASES),
        "in_production_qty": _match_column(columns, IN_PRODUCTION_ALIASES),
        "warehouse": _match_column(columns, WAREHOUSE_ALIASES),
        "price": _match_column(columns, PRICE_ALIASES),
    }
    if col["name"] is None:
        raise NomenclatureImportError(f"Не удалось найти колонку с наименованием среди {columns}")

    rows = []
    for _, row in df.iterrows():
        name = _clean_str(row.get(col["name"])) if col["name"] else None
        if not name:
            continue
        rows.append(
            {
                "code": _clean_str(row.get(col["code"])) if col["code"] else None,
                "cat_number": _clean_str(row.get(col["cat_number"])) if col["cat_number"] else None,
                "manufacturer": _clean_str(row.get(col["manufacturer"])) if col["manufacturer"] else None,
                "name": name,
                "unit": _clean_str(row.get(col["unit"])) if col["unit"] else None,
                "stock_qty": _clean_num(row.get(col["stock_qty"])) if col["stock_qty"] else None,
                "ordered_qty": _clean_num(row.get(col["ordered_qty"])) if col["ordered_qty"] else None,
                "reserved_qty": _clean_num(row.get(col["reserved_qty"])) if col["reserved_qty"] else None,
                "in_production_qty": (
                    _clean_num(row.get(col["in_production_qty"])) if col["in_production_qty"] else None
                ),
                "warehouse": _clean_str(row.get(col["warehouse"])) if col["warehouse"] else None,
                "price": _clean_num(row.get(col["price"])) if col["price"] else None,
            }
        )
    return rows


def parse_nomenclature_file(file_path: str) -> list[dict]:
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        engine = "xlrd" if ext == ".xls" else "openpyxl"
        df = pd.read_excel(file_path, engine=engine)
    elif ext == ".ods":
        df = pd.read_excel(file_path, engine="odf")
    elif ext == ".csv":
        last_error: Exception | None = None
        df = None
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                df = pd.read_csv(file_path, sep=None, engine="python", encoding=encoding)
                break
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_error = exc
        if df is None:
            raise NomenclatureImportError(f"Не удалось прочитать CSV (кодировка/разделитель): {last_error}")
    else:
        raise NomenclatureImportError(f"Неподдерживаемый формат файла: {ext}")

    return _dataframe_to_rows(df)


def import_nomenclature_file(file_path: str) -> dict:
    """Парсит файл и upsert-ит записи в NomenclatureEntry: совпадение по
    коду, иначе по каталожному номеру, иначе — новая запись. Так повторная
    загрузка обновлённой выгрузки не плодит дубликаты."""
    rows = parse_nomenclature_file(file_path)

    created = updated = 0
    for row in rows:
        entry = None
        if row["code"]:
            entry = NomenclatureEntry.query.filter_by(code=row["code"]).first()
        if entry is None and row["cat_number"]:
            entry = NomenclatureEntry.query.filter_by(cat_number=row["cat_number"]).first()

        if entry is None:
            entry = NomenclatureEntry(source="import")
            db.session.add(entry)
            created += 1
        else:
            updated += 1

        for field, value in row.items():
            setattr(entry, field, value)

    db.session.commit()
    return {"rows_parsed": len(rows), "created": created, "updated": updated}
