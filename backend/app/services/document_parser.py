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

# Таблица ставок за нормо-час по маркам ТС (см. parse_hourly_rate_table
# ниже) — образец файла от заказчика так и не пришёл, поэтому колонки тоже
# ищутся по алиасам заголовка, а не по конкретному имени/позиции: заказчик
# может назвать колонки "Марка"/"Марка ТС"/"Brand", "Ставка"/"Цена н/ч" — как
# ему удобно, а не так, как было в одном присланном примере.
MAKE_COLUMN_ALIASES = ["марка", "make", "brand", "марка тс", "марка автомобиля"]
RATE_COLUMN_ALIASES = ["ставка", "цена н/ч", "цена нормо-часа", "стоимость н/ч", "цена", "rate", "price", "стоимость"]

# Колонки печатной формы заказ-наряда 1С ("Выполненные работы"/"Расходная
# накладная", см. parse_repair_order_export ниже) — по алиасам заголовка, а
# не по фиксированной позиции. Раньше колонки читались строго по индексу
# (row[9]/row[10]/row[12] и т.п.) — это совпадало с ОДНИМ конкретным
# шаблоном отчёта 1С (реальный файл заказчика), но другая конфигурация 1С
# или версия отчёта вполне может расставить колонки иначе — тогда позиционное
# чтение молча подставляло бы норму часов в цену или наоборот, вместо того
# чтобы честно не найти колонку.
# Переиспользуем те же синонимы, что и generic-парсер выше (ARTICLE/NAME/
# QTY/PRICE_COLUMN_ALIASES), а не заводим более узкий отдельный список —
# "Наименование" в этой печатной форме означает то же самое, что и в любом
# другом договоре/накладной. Добавляем только то, чего там нет: "№ кат." —
# аббревиатура именно этого отчёта 1С для артикула/кода.
LABOR_CATALOG_CODE_ALIASES = ARTICLE_COLUMN_ALIASES + ["№ кат"]
LABOR_DESCRIPTION_ALIASES = NAME_COLUMN_ALIASES + ["работа", "операция"]
LABOR_HOURLY_RATE_ALIASES = ["цена н/ч", "цена нормо-часа", "цена за час", "стоимость н/ч"]
LABOR_NORM_HOURS_ALIASES = ["норма"]
LABOR_TOTAL_ALIASES = ["всего", "итого", "сумма"]

MATERIAL_ARTICLE_ALIASES = ARTICLE_COLUMN_ALIASES + ["№ кат"]
MATERIAL_NAME_ALIASES = NAME_COLUMN_ALIASES
MATERIAL_QTY_ALIASES = QTY_COLUMN_ALIASES
MATERIAL_PRICE_ALIASES = PRICE_COLUMN_ALIASES


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


def _dataframe_to_rate_lines(df: pd.DataFrame) -> list[dict]:
    columns = list(df.columns)
    make_col = _match_column(columns, MAKE_COLUMN_ALIASES)
    rate_col = _match_column(columns, RATE_COLUMN_ALIASES)

    if make_col is None:
        raise DocumentParseError(f"Не удалось найти колонку с маркой ТС среди {columns}")
    if rate_col is None:
        raise DocumentParseError(f"Не удалось найти колонку со ставкой за нормо-час среди {columns}")

    lines = []
    for _, row in df.iterrows():
        make = row.get(make_col)
        if pd.isna(make) or not str(make).strip():
            continue
        rate = _to_float(row.get(rate_col))
        if rate is None or rate <= 0:
            continue
        lines.append({"vehicle_make": str(make).strip(), "hourly_rate": rate})
    return lines


def parse_hourly_rate_table(file_path: str) -> list[dict]:
    """Таблица ставок за нормо-час по маркам ТС (для контрагента или
    договора, см. app/services/hourly_rate_import.py) — только табличные
    форматы (xlsx/xls/ods/csv), без docx/pdf: такая таблица на практике
    всегда простая электронная таблица, а не свободный документ со сканами.
    Каждая строка: {"vehicle_make": str, "hourly_rate": float}."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".xlsx", ".xlsm", ".xls"):
        df = _read_excel_df(file_path)
    elif ext == ".ods":
        df = _read_ods_df(file_path)
    elif ext == ".csv":
        df = _read_csv_df(file_path)
    else:
        raise DocumentParseError(f"Неподдерживаемый формат файла для таблицы ставок: {ext}")
    return _dataframe_to_rate_lines(df)


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


def _read_excel_df(file_path: str) -> pd.DataFrame:
    # .xls — старый бинарный формат (OLE2), openpyxl умеет только xlsx/xlsm
    # и молча падает на нём — нужен отдельный движок xlrd.
    ext = os.path.splitext(file_path)[1].lower()
    engine = "xlrd" if ext == ".xls" else "openpyxl"
    return pd.read_excel(file_path, engine=engine, dtype=str)


def _read_ods_df(file_path: str) -> pd.DataFrame:
    return pd.read_excel(file_path, engine="odf", dtype=str)


def _read_csv_df(file_path: str) -> pd.DataFrame:
    """Экспорт из 1С/банк-клиентов чаще всего — Windows-1251 и разделитель
    ';', а не запятая — поэтому не полагаемся на дефолты pandas."""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return pd.read_csv(file_path, sep=None, engine="python", encoding=encoding, dtype=str)
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise DocumentParseError(f"Не удалось прочитать CSV (кодировка/разделитель): {last_error}")


def parse_excel(file_path: str) -> list[dict]:
    return _dataframe_to_lines(_read_excel_df(file_path))


def parse_ods(file_path: str) -> list[dict]:
    return _dataframe_to_lines(_read_ods_df(file_path))


def parse_csv(file_path: str) -> list[dict]:
    return _dataframe_to_lines(_read_csv_df(file_path))


def extract_docx_tables(file_path: str) -> list[pd.DataFrame]:
    from docx import Document

    document = Document(file_path)
    tables: list[pd.DataFrame] = []
    for table in document.tables:
        rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
        if len(rows) < 2:
            continue
        header, *body = rows
        tables.append(pd.DataFrame(body, columns=header))
    return tables


def extract_pdf_tables(file_path: str) -> list[pd.DataFrame]:
    import pdfplumber

    tables: list[pd.DataFrame] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header, *rows = table
                tables.append(pd.DataFrame(rows, columns=header))
    return tables


def parse_docx(file_path: str) -> list[dict]:
    all_lines: list[dict] = []
    for df in extract_docx_tables(file_path):
        all_lines.extend(_dataframe_to_lines(df))
    return all_lines


def parse_pdf(file_path: str) -> list[dict]:
    all_lines: list[dict] = []
    for df in extract_pdf_tables(file_path):
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


def needs_ocr(file_path: str) -> bool:
    from app.services.ocr import is_image_extension

    ext = os.path.splitext(file_path)[1].lower()
    if is_image_extension(ext):
        return True
    if ext == ".pdf":
        try:
            return len(parse_pdf(file_path)) == 0
        except Exception:
            return True
    return False


def parse_document_with_ocr_fallback(file_path: str, llm_client, fields: list[str]) -> list[dict]:
    if not needs_ocr(file_path):
        return parse_document(file_path)

    from app.services.ocr import OcrError, extract_text

    try:
        raw_text = extract_text(file_path)
    except OcrError as exc:
        raise DocumentParseError(str(exc)) from exc
    if not raw_text.strip():
        raise DocumentParseError("Не удалось распознать текст в файле (пустой результат OCR)")

    try:
        rows = llm_client.extract_table_from_text(raw_text, fields)
    except Exception as exc:
        raise DocumentParseError(f"Не удалось извлечь таблицу из распознанного текста: {exc}") from exc

    numeric_fields = {"qty", "price", "stock_qty", "ordered_qty", "reserved_qty", "in_production_qty", "norm_hours"}
    cleaned = []
    for row in rows:
        if not any(row.values()):
            continue
        cleaned.append(
            {
                field: (_to_float(value) if field in numeric_fields else _clean(value))
                for field, value in row.items()
            }
        )
    return cleaned


_ORDER_RE = re.compile(r"Заказ-наряд\s*№\s*(\S+)\s*от\s*(\d{2}\.\d{2}\.\d{4})")
_VEHICLE_RE = re.compile(r"Автомобиль\s*:\s*(.+?)\s+гос\.\s*номер\s*:\s*(\S+)\s+VIN\s*:\s*(\S+)")
_YEAR_RE = re.compile(r"год\s*вып\.?\s*(\d{4})")


def _find_export_column(header_row: list, aliases: list[str]) -> int | None:
    """Индекс колонки в СЫРОЙ (без имён pandas) строке заголовка печатной
    формы 1С — по алиасам, см. комментарий у LABOR_*/MATERIAL_*_ALIASES."""
    for idx, cell in enumerate(header_row):
        if not isinstance(cell, str):
            continue
        norm = cell.strip().lower()
        if any(alias in norm for alias in aliases):
            return idx
    return None


def _export_cell(row: list, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_repair_order_export(file_path: str) -> dict | None:
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in (".xlsx", ".xlsm"):
        return None

    df = pd.read_excel(file_path, sheet_name=0, header=None, dtype=str, engine="openpyxl")
    rows = df.values.tolist()

    has_labor_section = any(any(isinstance(c, str) and "Выполненные работы по заказ-наряду" in c for c in row) for row in rows)
    has_materials_section = any(any(isinstance(c, str) and "Расходная накладная к заказ-наряду" in c for c in row) for row in rows)
    if not (has_labor_section or has_materials_section):
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
    labor_cols: dict[str, int | None] = {}
    material_cols: dict[str, int | None] = {}

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
                labor_cols = {
                    "catalog_code": _find_export_column(row, LABOR_CATALOG_CODE_ALIASES),
                    "description": _find_export_column(row, LABOR_DESCRIPTION_ALIASES),
                    "hourly_rate": _find_export_column(row, LABOR_HOURLY_RATE_ALIASES),
                    "norm_hours": _find_export_column(row, LABOR_NORM_HOURS_ALIASES),
                    "total": _find_export_column(row, LABOR_TOTAL_ALIASES),
                }
                if labor_cols["description"] is None:
                    logger.warning(
                        "parse_repair_order_export: не нашёл колонку с наименованием работы в заголовке %r — "
                        "раздел 'Выполненные работы' пропущен",
                        row,
                    )
                mode = "await_labor_index"
            continue
        if mode == "await_labor_index":
            mode = "labor"
            continue
        if mode == "labor":
            if c1 and c1.startswith("Итого работ"):
                mode = None
                continue
            if c1 and c1.isdigit() and labor_cols.get("description") is not None:
                labor_lines.append(
                    {
                        "description": _clean(_export_cell(row, labor_cols["description"])),
                        "catalog_code": _clean(_export_cell(row, labor_cols["catalog_code"])),
                        "hourly_rate": _to_float(_export_cell(row, labor_cols["hourly_rate"])),
                        "norm_hours": _to_float(_export_cell(row, labor_cols["norm_hours"])),
                        "total": _to_float(_export_cell(row, labor_cols["total"])),
                    }
                )
            continue

        if "Расходная накладная к заказ-наряду" in joined:
            mode = "await_materials_header"
            continue
        if mode == "await_materials_header":
            if c1 == "№":
                material_cols = {
                    "article": _find_export_column(row, MATERIAL_ARTICLE_ALIASES),
                    "name": _find_export_column(row, MATERIAL_NAME_ALIASES),
                    "qty": _find_export_column(row, MATERIAL_QTY_ALIASES),
                    "price": _find_export_column(row, MATERIAL_PRICE_ALIASES),
                }
                if material_cols["name"] is None:
                    logger.warning(
                        "parse_repair_order_export: не нашёл колонку с наименованием запчасти в заголовке %r — "
                        "раздел 'Расходная накладная' пропущен",
                        row,
                    )
                mode = "await_materials_index"
            continue
        if mode == "await_materials_index":
            mode = "materials"
            continue
        if mode == "materials":
            if c1 and (c1.startswith("Итого по странице материалов") or c1.startswith("Итого материалов")):
                mode = None
                continue
            if c1 and c1.isdigit() and material_cols.get("name") is not None:
                part_lines.append(
                    {
                        "article": _clean(_export_cell(row, material_cols["article"])),
                        "name": _clean(_export_cell(row, material_cols["name"])),
                        "qty": _to_float(_export_cell(row, material_cols["qty"])),
                        "price": _to_float(_export_cell(row, material_cols["price"])),
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
