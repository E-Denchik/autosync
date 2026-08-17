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
    normalized = {c: str(c).strip().lower() for c in columns if not str(c).strip().lower().startswith("unnamed")}
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


NOMENCLATURE_FIELDS = [
    "code",
    "cat_number",
    "manufacturer",
    "name",
    "unit",
    "stock_qty",
    "ordered_qty",
    "reserved_qty",
    "in_production_qty",
    "warehouse",
    "price",
]


def parse_nomenclature_file(file_path: str, llm_client=None) -> list[dict]:
    from app.services.document_parser import extract_docx_tables, extract_pdf_tables, needs_ocr

    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        engine = "xlrd" if ext == ".xls" else "openpyxl"
        df = pd.read_excel(file_path, engine=engine, dtype=str)
        return _dataframe_to_rows(df)
    if ext == ".ods":
        df = pd.read_excel(file_path, engine="odf", dtype=str)
        return _dataframe_to_rows(df)
    if ext == ".csv":
        last_error: Exception | None = None
        df = None
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                df = pd.read_csv(file_path, sep=None, engine="python", encoding=encoding, dtype=str)
                break
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_error = exc
        if df is None:
            raise NomenclatureImportError(f"Не удалось прочитать CSV (кодировка/разделитель): {last_error}")
        return _dataframe_to_rows(df)
    if ext == ".docx":
        rows = []
        for table_df in extract_docx_tables(file_path):
            rows.extend(_dataframe_to_rows(table_df))
        return rows
    if ext == ".pdf" and not needs_ocr(file_path):
        rows = []
        for table_df in extract_pdf_tables(file_path):
            rows.extend(_dataframe_to_rows(table_df))
        return rows
    if needs_ocr(file_path):
        if llm_client is None:
            raise NomenclatureImportError(
                "Файл требует распознавания текста (скан/фото или PDF без текстового слоя), "
                "но LLM для структурирования результата недоступен"
            )
        return _extract_via_ocr(file_path, llm_client)

    raise NomenclatureImportError(f"Неподдерживаемый формат файла: {ext}")


def _extract_via_ocr(file_path: str, llm_client) -> list[dict]:
    from app.services.ocr import OcrError, extract_text

    try:
        raw_text = extract_text(file_path)
    except OcrError as exc:
        raise NomenclatureImportError(str(exc)) from exc
    if not raw_text.strip():
        raise NomenclatureImportError("Не удалось распознать текст в файле (пустой результат OCR)")

    try:
        rows = llm_client.extract_table_from_text(raw_text, NOMENCLATURE_FIELDS)
    except Exception as exc:
        raise NomenclatureImportError(f"Не удалось извлечь таблицу из распознанного текста: {exc}") from exc

    numeric_fields = {"stock_qty", "ordered_qty", "reserved_qty", "in_production_qty", "price"}
    cleaned = []
    for row in rows:
        name = _clean_str(row.get("name"))
        if not name:
            continue
        cleaned.append(
            {
                field: (_clean_num(value) if field in numeric_fields else _clean_str(value))
                for field, value in {**row, "name": name}.items()
            }
        )
    return cleaned


def import_nomenclature_file(file_path: str, llm_client=None) -> dict:
    """Парсит файл и upsert-ит записи в NomenclatureEntry: совпадение по
    коду, иначе по каталожному номеру, иначе — новая запись. Так повторная
    загрузка обновлённой выгрузки не плодит дубликаты."""
    rows = parse_nomenclature_file(file_path, llm_client)

    codes = {row["code"] for row in rows if row["code"]}
    cat_numbers = {row["cat_number"] for row in rows if row["cat_number"]}
    by_code = {e.code: e for e in NomenclatureEntry.query.filter(NomenclatureEntry.code.in_(codes)).all()} if codes else {}
    by_cat_number = (
        {e.cat_number: e for e in NomenclatureEntry.query.filter(NomenclatureEntry.cat_number.in_(cat_numbers)).all()}
        if cat_numbers
        else {}
    )

    created = updated = 0
    new_entries = []
    for row in rows:
        entry = None
        if row["code"]:
            entry = by_code.get(row["code"])
        if entry is None and row["cat_number"]:
            entry = by_cat_number.get(row["cat_number"])

        if entry is None:
            entry = NomenclatureEntry(source="import")
            new_entries.append(entry)
            if row["code"]:
                by_code[row["code"]] = entry
            if row["cat_number"]:
                by_cat_number.setdefault(row["cat_number"], entry)
            created += 1
        else:
            updated += 1

        for field, value in row.items():
            setattr(entry, field, value)

    db.session.add_all(new_entries)
    db.session.commit()
    return {"rows_parsed": len(rows), "created": created, "updated": updated}
