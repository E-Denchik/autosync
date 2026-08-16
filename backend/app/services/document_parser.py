"""Парсинг договоров и заказ-нарядов в структурированные таблицы. Поддержаны
Excel (xlsx/xlsm/xls), CSV, OpenDocument (ods), Word (docx) и PDF — у разных
контрагентов и СТО документооборот ведётся в разных форматах, и требовать
от пользователя конвертировать всё в один формат вручную неудобно.

Каждая строка приводится к общему формату:
    {"article": str | None, "name": str, "qty": float | None, "price": float | None}

Эвристики распознавания колонок написаны широко (RU-синонимы), потому что
формат договоров у разных контрагентов не стандартизован. Позиции, которые
не удалось уверенно распарсить, всё равно возвращаются — с article=None —
чтобы matcher.py мог попытаться сопоставить их через LLM, а ReviewMatches
показал их человеку.
"""

from __future__ import annotations

import logging
import os
import re

import pandas as pd

logger = logging.getLogger(__name__)

ARTICLE_COLUMN_ALIASES = ["артикул", "article", "код", "sku", "парт", "part_number"]
NAME_COLUMN_ALIASES = ["наименование", "название", "name", "описание", "товар", "запчасть"]
QTY_COLUMN_ALIASES = ["кол-во", "количество", "qty", "quantity", "шт"]
PRICE_COLUMN_ALIASES = ["цена", "price", "стоимость", "сумма"]


class DocumentParseError(RuntimeError):
    pass


def _match_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {c: str(c).strip().lower() for c in columns if not str(c).strip().lower().startswith("unnamed")}
    for col, norm in normalized.items():
        if any(alias in norm for alias in aliases):
            return col
    return None


def _dataframe_to_lines(df: pd.DataFrame) -> list[dict]:
    columns = list(df.columns)
    article_col = _match_column(columns, ARTICLE_COLUMN_ALIASES)
    name_col = _match_column(columns, NAME_COLUMN_ALIASES)
    qty_col = _match_column(columns, QTY_COLUMN_ALIASES)
    price_col = _match_column(columns, PRICE_COLUMN_ALIASES)

    if name_col is None:
        raise DocumentParseError(f"Не удалось найти колонку с наименованием среди {columns}")

    lines = []
    for _, row in df.iterrows():
        name = row.get(name_col)
        if pd.isna(name) or not str(name).strip():
            continue
        lines.append(
            {
                "article": _clean(row.get(article_col)) if article_col else None,
                "name": str(name).strip(),
                "qty": _to_float(row.get(qty_col)) if qty_col else None,
                "price": _to_float(row.get(price_col)) if price_col else None,
            }
        )
    return lines


def _clean(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value).strip() or None


def _to_float(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def parse_excel(file_path: str) -> list[dict]:
    # .xls — старый бинарный формат (OLE2), openpyxl умеет только xlsx/xlsm
    # и молча падает на нём — нужен отдельный движок xlrd.
    ext = os.path.splitext(file_path)[1].lower()
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    df = pd.read_excel(file_path, engine=engine, dtype=str)
    return _dataframe_to_lines(df)


def parse_ods(file_path: str) -> list[dict]:
    df = pd.read_excel(file_path, engine="odf", dtype=str)
    return _dataframe_to_lines(df)


def parse_csv(file_path: str) -> list[dict]:
    """Экспорт из 1С/банк-клиентов чаще всего — Windows-1251 и разделитель
    ';', а не запятая — поэтому не полагаемся на дефолты pandas."""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            df = pd.read_csv(file_path, sep=None, engine="python", encoding=encoding, dtype=str)
            return _dataframe_to_lines(df)
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise DocumentParseError(f"Не удалось прочитать CSV (кодировка/разделитель): {last_error}")


def parse_docx(file_path: str) -> list[dict]:
    from docx import Document

    document = Document(file_path)
    all_lines: list[dict] = []
    for table in document.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(rows) < 2:
            continue
        header, *body = rows
        df = pd.DataFrame(body, columns=header)
        all_lines.extend(_dataframe_to_lines(df))
    return all_lines


def parse_pdf(file_path: str) -> list[dict]:
    import pdfplumber

    all_lines: list[dict] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header, *rows = table
                df = pd.DataFrame(rows, columns=header)
                all_lines.extend(_dataframe_to_lines(df))
    return all_lines


_PARSERS = {
    ".xlsx": parse_excel,
    ".xlsm": parse_excel,
    ".xls": parse_excel,
    ".ods": parse_ods,
    ".csv": parse_csv,
    ".docx": parse_docx,
    ".pdf": parse_pdf,
}


def parse_document(file_path: str) -> list[dict]:
    ext = os.path.splitext(file_path)[1].lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise DocumentParseError(f"Неподдерживаемый формат файла: {ext}")
    return parser(file_path)


_ORDER_RE = re.compile(r"Заказ-наряд\s*№\s*(\S+)\s*от\s*(\d{2}\.\d{2}\.\d{4})")
_VEHICLE_RE = re.compile(r"Автомобиль\s*:\s*(.+?)\s+гос\.\s*номер\s*:\s*(\S+)\s+VIN\s*:\s*(\S+)")
_YEAR_RE = re.compile(r"год\s*вып\.?\s*(\d{4})")


def parse_repair_order_export(file_path: str) -> dict | None:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".xlsx", ".xlsm"):
        return None

    df = pd.read_excel(file_path, sheet_name=0, header=None, dtype=str, engine="openpyxl")
    rows = df.values.tolist()

    has_labor_section = any(any(isinstance(c, str) and "Выполненные работы по заказ-наряду" in c for c in row) for row in rows)
    has_materials_section = any(any(isinstance(c, str) and "Расходная накладная к заказ-наряду" in c for c in row) for row in rows)
    if not (has_labor_section and has_materials_section):
        return None

    meta = {
        "order_number": None,
        "order_date": None,
        "vehicle_make": None,
        "vehicle_model": None,
        "vehicle_vin": None,
        "vehicle_year": None,
    }
    labor_lines: list[dict] = []
    part_lines: list[dict] = []
    mode = None

    for row in rows:
        joined = " ".join(c for c in row if isinstance(c, str))
        c1 = _clean(row[1]) if len(row) > 1 else None

        if meta["order_number"] is None:
            m = _ORDER_RE.search(joined)
            if m:
                meta["order_number"] = m.group(1)
                meta["order_date"] = m.group(2)

        if meta["vehicle_make"] is None:
            m = _VEHICLE_RE.search(joined)
            if m:
                make_model = m.group(1).split(None, 1)
                meta["vehicle_make"] = make_model[0] if make_model else None
                meta["vehicle_model"] = make_model[1] if len(make_model) > 1 else None
                meta["vehicle_vin"] = m.group(3)
                year_m = _YEAR_RE.search(joined)
                if year_m:
                    meta["vehicle_year"] = int(year_m.group(1))

        if "Выполненные работы по заказ-наряду" in joined:
            mode = "await_labor_header"
            continue
        if mode == "await_labor_header":
            if c1 == "№":
                mode = "await_labor_index"
            continue
        if mode == "await_labor_index":
            mode = "labor"
            continue
        if mode == "labor":
            if c1 and c1.startswith("Итого работ"):
                mode = None
                continue
            if c1 and c1.isdigit():
                labor_lines.append(
                    {
                        "description": _clean(row[3]) if len(row) > 3 else None,
                        "catalog_code": _clean(row[2]) if len(row) > 2 else None,
                        "hourly_rate": _to_float(row[9]) if len(row) > 9 else None,
                        "norm_hours": _to_float(row[10]) if len(row) > 10 else None,
                        "total": _to_float(row[12]) if len(row) > 12 else None,
                    }
                )
            continue

        if "Расходная накладная к заказ-наряду" in joined:
            mode = "await_materials_header"
            continue
        if mode == "await_materials_header":
            if c1 == "№":
                mode = "await_materials_index"
            continue
        if mode == "await_materials_index":
            mode = "materials"
            continue
        if mode == "materials":
            if c1 and (c1.startswith("Итого по странице материалов") or c1.startswith("Итого материалов")):
                mode = None
                continue
            if c1 and c1.isdigit():
                part_lines.append(
                    {
                        "article": _clean(row[2]) if len(row) > 2 else None,
                        "name": _clean(row[3]) if len(row) > 3 else None,
                        "qty": _to_float(row[9]) if len(row) > 9 else None,
                        "price": _to_float(row[11]) if len(row) > 11 else None,
                    }
                )
            continue

    if not labor_lines and not part_lines:
        return None

    return {"meta": meta, "labor_lines": labor_lines, "part_lines": part_lines}


_CATALOG_TITLE_MARKER = "Марка (модель) технического средства"


def parse_price_catalog_by_brand(file_path: str, vehicle_make: str) -> list[dict] | None:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".xlsx", ".xlsm"):
        return None

    import openpyxl

    wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)

    brand_sheets: dict[str, str] = {}
    for name in wb.sheetnames:
        ws = wb[name]
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        title = str((first_row[0] if first_row else "") or "")
        if _CATALOG_TITLE_MARKER not in title:
            continue
        remainder = title.replace(_CATALOG_TITLE_MARKER, "")
        for brand in remainder.replace(",", " и ").split(" и "):
            brand = brand.strip().upper()
            if brand:
                brand_sheets[brand] = name

    if not brand_sheets:
        return None

    target = (vehicle_make or "").strip().upper()
    matched_sheet = brand_sheets.get(target)
    if not matched_sheet:
        logger.warning(
            "Марка %r не найдена в каталоге %s (доступны: %s) — сопоставление пойдёт только по расходным материалам",
            vehicle_make,
            file_path,
            sorted(brand_sheets),
        )

    results: list[dict] = []

    if matched_sheet:
        ws = wb[matched_sheet]
        for row in ws.iter_rows(min_row=3, values_only=True):
            name = _clean(row[1]) if len(row) > 1 else None
            if not name:
                continue
            results.append(
                {
                    "article": _clean(row[3]) if len(row) > 3 else None,
                    "name": name,
                    "qty": None,
                    "price": _to_float(row[2]) if len(row) > 2 else None,
                }
            )

    if "Расходные материалы" in wb.sheetnames:
        ws = wb["Расходные материалы"]
        for row in ws.iter_rows(min_row=3, values_only=True):
            name = _clean(row[1]) if len(row) > 1 else None
            if not name:
                continue
            results.append(
                {
                    "article": None,
                    "name": name,
                    "qty": None,
                    "price": _to_float(row[3]) if len(row) > 3 else None,
                }
            )

    return results
