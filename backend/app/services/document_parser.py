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

import os

import pandas as pd

ARTICLE_COLUMN_ALIASES = ["артикул", "article", "код", "sku", "парт", "part_number"]
NAME_COLUMN_ALIASES = ["наименование", "название", "name", "описание", "товар", "запчасть"]
QTY_COLUMN_ALIASES = ["кол-во", "количество", "qty", "quantity", "шт"]
PRICE_COLUMN_ALIASES = ["цена", "price", "стоимость", "сумма"]


class DocumentParseError(RuntimeError):
    pass


def _match_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {c: str(c).strip().lower() for c in columns}
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
    df = pd.read_excel(file_path, engine=engine)
    return _dataframe_to_lines(df)


def parse_ods(file_path: str) -> list[dict]:
    df = pd.read_excel(file_path, engine="odf")
    return _dataframe_to_lines(df)


def parse_csv(file_path: str) -> list[dict]:
    """Экспорт из 1С/банк-клиентов чаще всего — Windows-1251 и разделитель
    ';', а не запятая — поэтому не полагаемся на дефолты pandas."""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            df = pd.read_csv(file_path, sep=None, engine="python", encoding=encoding)
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
