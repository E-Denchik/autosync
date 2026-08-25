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
# ниже) — колонки ищутся по алиасам заголовка, как и везде в этом файле.
# Реальный файл заказчика (приложение к тендерному контракту, .docx) кладёт
# марку и модель ОДНОЙ колонкой "Марка (модель)" — алиас "марка" ловит её
# по подстроке без отдельной записи. MODEL_COLUMN_ALIASES — на случай, если
# в файле марка и модель всё же разнесены по разным колонкам.
MAKE_COLUMN_ALIASES = ["марка", "make", "brand", "марка тс", "марка автомобиля"]
MODEL_COLUMN_ALIASES = ["модель"]
RATE_COLUMN_ALIASES = ["ставка", "цена н/ч", "цена нормо-часа", "стоимость н/ч", "цена", "rate", "price", "стоимость"]
# Строка "ИТОГО ..."/"Всего ..." в конце такой таблицы — это сумма по
# таблице, а не реальная ставка (реальный файл заказчика: "ИТОГО с учетом
# аукционного снижения (55%): ... 6209.99" — своя "марка" и число, похожее
# на ставку, но это агрегат, который выдал бы мусорную ставку в 6000+ ₽).
_TOTAL_ROW_MARKERS = ("итого", "всего")

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
LABOR_NORM_HOURS_ALIASES = ["норма", "нормо-час", "нормочас"]
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


def _split_make_model(text: str) -> tuple[str, str | None]:
    """"Hyundai Accent" -> ("Hyundai", "Accent"); "Chevrolet" -> ("Chevrolet", None).
    Эвристика (первое слово — марка, остаток — модель) верна для подавляющего
    большинства марок ("Toyota Land Cruiser", "Hyundai Santa Fe"); двусловные
    марки без модели в одной ячейке ("Great Wall") — известное исключение,
    которое эта эвристика не отличит от "марка+модель"."""
    parts = text.split(None, 1)
    if len(parts) == 2:
        return parts[0], parts[1].strip()
    return parts[0], None


def _expand_make_cell(make_text: str, value: float, model_text: str | None = None) -> list[dict]:
    """Одна "ячейка" с маркой(-ами) + число (ставка в рублях ИЛИ норма в
    часах — вызывающий код сам знает, что это такое) -> одна или несколько
    строк {vehicle_make, vehicle_model, value}. Если модель уже известна
    отдельно (своя колонка, или её уже выделила LLM при OCR-разборе) —
    доверяем ей как есть. Иначе разбираем make_text сами: одна ячейка может
    перечислять сразу несколько марок/моделей с одинаковым числом через
    запятую (реальный файл заказчика: "Renault Sandero, Nissan Almera
    Classik, ..., Hyundai Accent, Hyundai Sonata" — все по одной цене)."""
    if model_text:
        return [{"vehicle_make": make_text, "vehicle_model": model_text, "value": value}]

    lines = []
    for segment in make_text.split(","):
        segment = segment.strip()
        if not segment:
            continue
        make, model = _split_make_model(segment)
        lines.append({"vehicle_make": make, "vehicle_model": model, "value": value})
    return lines


def _dataframe_to_rate_lines(df: pd.DataFrame) -> list[dict]:
    columns = list(df.columns)
    make_col = _match_column(columns, MAKE_COLUMN_ALIASES)
    model_col = _match_column(columns, MODEL_COLUMN_ALIASES)
    rate_col = _match_column(columns, RATE_COLUMN_ALIASES)
    if model_col == make_col:
        # "Марка (модель)" одной колонкой matches оба алиаса сразу — это НЕ
        # отдельная колонка модели, а комбинированная ячейка (см.
        # _expand_make_cell).
        model_col = None

    if make_col is None:
        raise DocumentParseError(f"Не удалось найти колонку с маркой ТС среди {columns}")
    if rate_col is None:
        raise DocumentParseError(f"Не удалось найти колонку со ставкой за нормо-час среди {columns}")

    lines = []
    for _, row in df.iterrows():
        make_cell = row.get(make_col)
        if pd.isna(make_cell) or not str(make_cell).strip():
            continue
        make_text = str(make_cell).strip()
        if any(marker in make_text.lower() for marker in _TOTAL_ROW_MARKERS):
            continue

        rate = _to_float(row.get(rate_col))
        if rate is None or rate <= 0:
            continue

        model_text = _clean(row.get(model_col)) if model_col else None
        for expanded in _expand_make_cell(make_text, rate, model_text):
            lines.append(
                {
                    "vehicle_make": expanded["vehicle_make"],
                    "vehicle_model": expanded["vehicle_model"],
                    "hourly_rate": expanded["value"],
                }
            )
    return lines


def parse_hourly_rate_table(file_path: str, llm_client=None) -> list[dict]:
    """Таблица ставок за нормо-час по маркам/моделям ТС (для контрагента или
    договора, см. app/services/hourly_rate_import.py). Каждая строка:
    {"vehicle_make": str, "vehicle_model": str | None, "hourly_rate": float}.

    Поддержаны и простые таблицы (xlsx/xls/ods/csv — одна колонка "Марка",
    одна "Ставка"), и печатная форма приложения к тендерному контракту
    (docx — реальный файл заказчика: таблица "Марка (модель) | Цена" внутри
    Word-документа, возможно несколько таблиц в файле, включая пустые
    служебные — из них просто не наберётся ни одной строки, это не ошибка),
    и PDF с текстовым слоем — тем же путём, что и docx.

    Скан/фото (jpg/png) и PDF БЕЗ текстового слоя (сфотографированное
    бумажное приложение к тендеру — вполне реальный случай, не только
    цифровой оригинал) идут через OCR + LLM-извлечение — тот же путь, что
    и распознавание сканов заказ-нарядов/договоров (см. services/ocr.py,
    LLMClient.extract_table_from_text). Для этого пути нужен llm_client —
    если он не передан, а файл оказался сканом, вернётся понятная ошибка,
    а не тихая пустота."""
    from app.services.ocr import is_image_extension

    ext = os.path.splitext(file_path)[1].lower()
    if is_image_extension(ext):
        return _parse_rate_table_via_ocr(file_path, llm_client)

    if ext in (".xlsx", ".xlsm", ".xls"):
        dataframes = [_read_excel_df(file_path)]
    elif ext == ".ods":
        dataframes = [_read_ods_df(file_path)]
    elif ext == ".csv":
        dataframes = [_read_csv_df(file_path)]
    elif ext == ".docx":
        dataframes = extract_docx_tables(file_path)
    elif ext == ".pdf":
        dataframes = extract_pdf_tables(file_path)
    else:
        raise DocumentParseError(f"Неподдерживаемый формат файла для таблицы ставок: {ext}")

    lines: list[dict] = []
    last_error: DocumentParseError | None = None
    for df in dataframes:
        try:
            lines.extend(_dataframe_to_rate_lines(df))
        except DocumentParseError as exc:
            last_error = exc
    if lines:
        return lines

    if ext == ".pdf":
        # Ни одна таблица не нашлась текстом — похоже на скан без
        # текстового слоя, а не настоящий PDF-документ с таблицей.
        return _parse_rate_table_via_ocr(file_path, llm_client)

    raise last_error or DocumentParseError("В файле не найдено ни одной таблицы со ставками")


def _parse_rate_table_via_ocr(file_path: str, llm_client) -> list[dict]:
    if llm_client is None:
        raise DocumentParseError(
            "Файл похож на скан/фото — чтобы распознать таблицу ставок, нужна выбранная LLM-модель"
        )

    from app.services.ocr import OcrError, extract_text

    try:
        raw_text = extract_text(file_path)
    except OcrError as exc:
        raise DocumentParseError(str(exc)) from exc
    if not raw_text.strip():
        raise DocumentParseError("Не удалось распознать текст в файле (пустой результат OCR)")

    try:
        rows = llm_client.extract_table_from_text(raw_text, ["vehicle_make", "vehicle_model", "hourly_rate"])
    except Exception as exc:
        raise DocumentParseError(f"Не удалось извлечь таблицу ставок из распознанного текста: {exc}") from exc

    lines: list[dict] = []
    for row in rows:
        make_text = _clean(row.get("vehicle_make"))
        if not make_text:
            continue
        if any(marker in make_text.lower() for marker in _TOTAL_ROW_MARKERS):
            continue
        rate = _to_float(row.get("hourly_rate"))
        if rate is None or rate <= 0:
            continue
        model_text = _clean(row.get("vehicle_model"))
        for expanded in _expand_make_cell(make_text, rate, model_text):
            lines.append(
                {
                    "vehicle_make": expanded["vehicle_make"],
                    "vehicle_model": expanded["vehicle_model"],
                    "hourly_rate": expanded["value"],
                }
            )

    if not lines:
        raise DocumentParseError("Не удалось найти ни одной ставки в распознанном тексте")
    return lines


def _dataframe_to_labor_catalog_lines(df: pd.DataFrame) -> list[dict]:
    columns = list(df.columns)
    make_col = _match_column(columns, MAKE_COLUMN_ALIASES)
    model_col = _match_column(columns, MODEL_COLUMN_ALIASES)
    operation_col = _match_column(columns, LABOR_DESCRIPTION_ALIASES)
    norm_hours_col = _match_column(columns, LABOR_NORM_HOURS_ALIASES)
    if model_col == make_col:
        model_col = None  # "Марка (модель)" одной колонкой — см. _dataframe_to_rate_lines

    if make_col is None:
        raise DocumentParseError(f"Не удалось найти колонку с маркой ТС среди {columns}")
    if operation_col is None:
        raise DocumentParseError(f"Не удалось найти колонку с операцией среди {columns}")
    if norm_hours_col is None:
        raise DocumentParseError(f"Не удалось найти колонку с нормо-часами среди {columns}")

    lines = []
    for _, row in df.iterrows():
        make_text = _clean(row.get(make_col))
        operation_text = _clean(row.get(operation_col))
        if not make_text or not operation_text:
            continue
        if any(marker in make_text.lower() for marker in _TOTAL_ROW_MARKERS):
            continue

        norm_hours = _to_float(row.get(norm_hours_col))
        if norm_hours is None or norm_hours <= 0:
            continue

        model_text = _clean(row.get(model_col)) if model_col else None
        # Марка одной ячейкой может перечислять несколько марок/моделей через
        # запятую (см. _expand_make_cell) — та же операция и норма относится
        # к каждой из них.
        for expanded in _expand_make_cell(make_text, norm_hours, model_text):
            lines.append(
                {
                    "vehicle_make": expanded["vehicle_make"],
                    "vehicle_model": expanded["vehicle_model"],
                    "operation_name": operation_text,
                    "norm_hours": expanded["value"],
                }
            )
    return lines


def parse_labor_catalog_table(file_path: str, llm_client=None) -> list[dict]:
    """Таблица справочника нормо-часов (операция + норма часов по маркам/
    моделям ТС, см. app/models/labor_catalog.py) — тот же набор форматов и
    те же эвристики распознавания колонок, что и parse_hourly_rate_table
    (см. её докстринг), только вместо ставки в рублях — норма в часах, и
    обязательна колонка с названием операции. Каждая строка:
    {"vehicle_make": str, "vehicle_model": str | None, "operation_name": str,
    "norm_hours": float}."""
    from app.services.ocr import is_image_extension

    ext = os.path.splitext(file_path)[1].lower()
    if is_image_extension(ext):
        return _parse_labor_catalog_via_ocr(file_path, llm_client)

    if ext in (".xlsx", ".xlsm", ".xls"):
        dataframes = [_read_excel_df(file_path)]
    elif ext == ".ods":
        dataframes = [_read_ods_df(file_path)]
    elif ext == ".csv":
        dataframes = [_read_csv_df(file_path)]
    elif ext == ".docx":
        dataframes = extract_docx_tables(file_path)
    elif ext == ".pdf":
        dataframes = extract_pdf_tables(file_path)
    else:
        raise DocumentParseError(f"Неподдерживаемый формат файла для справочника нормо-часов: {ext}")

    lines: list[dict] = []
    last_error: DocumentParseError | None = None
    for df in dataframes:
        try:
            lines.extend(_dataframe_to_labor_catalog_lines(df))
        except DocumentParseError as exc:
            last_error = exc
    if lines:
        return lines

    if ext == ".pdf":
        return _parse_labor_catalog_via_ocr(file_path, llm_client)

    raise last_error or DocumentParseError("В файле не найдено ни одной строки с нормо-часами")


def _parse_labor_catalog_via_ocr(file_path: str, llm_client) -> list[dict]:
    if llm_client is None:
        raise DocumentParseError(
            "Файл похож на скан/фото — чтобы распознать справочник нормо-часов, нужна выбранная LLM-модель"
        )

    from app.services.ocr import OcrError, extract_text

    try:
        raw_text = extract_text(file_path)
    except OcrError as exc:
        raise DocumentParseError(str(exc)) from exc
    if not raw_text.strip():
        raise DocumentParseError("Не удалось распознать текст в файле (пустой результат OCR)")

    try:
        rows = llm_client.extract_table_from_text(
            raw_text, ["vehicle_make", "vehicle_model", "operation_name", "norm_hours"]
        )
    except Exception as exc:
        raise DocumentParseError(f"Не удалось извлечь таблицу нормо-часов из распознанного текста: {exc}") from exc

    lines: list[dict] = []
    for row in rows:
        make_text = _clean(row.get("vehicle_make"))
        operation_text = _clean(row.get("operation_name"))
        if not make_text or not operation_text:
            continue
        if any(marker in make_text.lower() for marker in _TOTAL_ROW_MARKERS):
            continue
        norm_hours = _to_float(row.get("norm_hours"))
        if norm_hours is None or norm_hours <= 0:
            continue
        model_text = _clean(row.get("vehicle_model"))
        for expanded in _expand_make_cell(make_text, norm_hours, model_text):
            lines.append(
                {
                    "vehicle_make": expanded["vehicle_make"],
                    "vehicle_model": expanded["vehicle_model"],
                    "operation_name": operation_text,
                    "norm_hours": expanded["value"],
                }
            )

    if not lines:
        raise DocumentParseError("Не удалось найти ни одной строки с нормо-часами в распознанном тексте")
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
    ';', а не запятая — поэтому не полагаемся на дефолты pandas.

    ';' пробуем ЯВНО первым, а не сразу автоопределение (sep=None): у него
    сносит крышу, стоит запятой встретиться где-то в самих данных — например
    в заголовке "Цена, руб." или в ячейке "Renault Sandero, Nissan Almera,
    ..." (реальный случай — марки через запятую в одной ячейке ставок). На
    маленькой выборке sep=None иногда решает, что разделитель — запятая, и
    падает на первой же строке с "лишней" запятой ("Expected N fields...
    saw M"), хотя реальный разделитель во всём файле — ';'."""
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        for sep in (";", None):
            try:
                df = pd.read_csv(file_path, sep=sep, engine="python", encoding=encoding, dtype=str)
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_error = exc
                continue
            if df.shape[1] > 1:
                return df
            last_error = last_error or ValueError("не удалось определить разделитель")
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
# "гос. номер: ..." между маркой и VIN есть не во всех выгрузках (см.
# testdata/repair_order_1_final.xlsx — там просто "Автомобиль: MAKE MODEL
# VIN: ..."), поэтому этот кусок необязательный.
_VEHICLE_RE = re.compile(r"Автомобиль\s*:\s*(.+?)\s+(?:гос\.\s*номер\s*:\s*(\S+)\s+)?VIN\s*:\s*(\S+)")
# Год либо "год вып. 2011", либо просто "2011 г." (см. тот же файл).
_YEAR_RE = re.compile(r"год\s*вып\.?\s*(\d{4})|(\d{4})\s*г\.?\b")


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


def _find_number_column(row: list) -> int | None:
    """Позиция колонки "№" в строке заголовка раздела — НЕ всегда row[1]:
    выгрузки 1С обычно вставляют пустую колонку A перед номером (тогда "№"
    в колонке B/index 1), но встречаются и формы без неё, где "№" сразу в
    колонке A/index 0 (см. testdata/repair_order_1_final.xlsx). Ищем по
    всей строке, а не по фиксированному индексу."""
    for idx, cell in enumerate(row):
        if _clean(cell) == "№":
            return idx
    return None


def _looks_like_data_row(row: list, key_col: int | None) -> bool:
    """Отличает первую строку РЕАЛЬНЫХ данных от необязательной строки-
    легенды с номерами колонок ("1 2 3 ... 9"), которую некоторые печатные
    формы 1С вставляют сразу под заголовком раздела, а некоторые — нет (см.
    testdata/repair_order_1_final.xlsx, где данные идут сразу после
    заголовка). В строке-легенде интересующая нас колонка (наименование
    работы/запчасти) содержит такой же короткий номер, как и остальные —
    отличить можно только по тому, что там не текст, а число."""
    if key_col is None:
        return False
    value = _clean(_export_cell(row, key_col))
    if not value:
        return False
    return not value.replace(".", "", 1).isdigit()


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
    labor_num_col: int | None = None
    material_num_col: int | None = None

    for row in rows:
        joined = " ".join(c for c in row if isinstance(c, str))

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
                    meta["vehicle_year"] = int(year_m.group(1) or year_m.group(2))

        if "Выполненные работы по заказ-наряду" in joined:
            mode = "await_labor_header"
            continue
        if mode == "await_labor_header":
            num_col = _find_number_column(row)
            if num_col is not None:
                labor_num_col = num_col
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
            # Строка-легенда номеров колонок под заголовком есть не во всех
            # выгрузках (см. _looks_like_data_row) — если её нет, эта же
            # строка уже данные, и её нельзя пропускать.
            mode = "labor"
            if _looks_like_data_row(row, labor_cols.get("description")):
                pass  # не continue — обработать эту же строку как данные ниже
            else:
                continue
        if mode == "labor":
            if "Итого работ" in joined:
                mode = None
                continue
            num_val = _clean(_export_cell(row, labor_num_col))
            if num_val and num_val.isdigit() and labor_cols.get("description") is not None:
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
            num_col = _find_number_column(row)
            if num_col is not None:
                material_num_col = num_col
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
            if _looks_like_data_row(row, material_cols.get("name")):
                pass  # не continue — обработать эту же строку как данные ниже
            else:
                continue
        if mode == "materials":
            if any(
                marker in joined
                for marker in ("Итого по странице материалов", "Итого материалов", "Итого запчасти")
            ):
                mode = None
                continue
            num_val = _clean(_export_cell(row, material_num_col))
            if num_val and num_val.isdigit() and material_cols.get("name") is not None:
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


def parse_price_catalog_by_brand(file_path: str, vehicle_make: str | None) -> list[dict] | None:
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
    if target:
        matched_sheets = [brand_sheets[target]] if target in brand_sheets else []
        if not matched_sheets:
            logger.warning(
                "Марка %r не найдена в каталоге %s (доступны: %s) — сопоставление пойдёт только по расходным материалам",
                vehicle_make,
                file_path,
                sorted(brand_sheets),
            )
    else:
        # Марка не задана — файл разом по нескольким маркам (см. sheetnames
        # выше), и ни одна из них не "более правильная" по умолчанию.
        # Раньше в этом случае функция вообще не вызывалась (см. вызывающий
        # код) и разбор уходил в общий парсер одной таблицы, который эту
        # структуру (строка-заголовок с маркой + отдельная строка с
        # колонками) не понимает и падает с "не удалось найти колонку с
        # наименованием" — реальный собранный руками файл заказчика именно
        # так и падал. Раз колонка "Марка" у ContractPart всё равно не
        # хранится (запчасти различаются по артикулу, а не по марке), для
        # запчастей безопасно и правильно просто взять ВСЕ найденные листы.
        seen_sheets: set[str] = set()
        matched_sheets = []
        for sheet_name in brand_sheets.values():
            if sheet_name not in seen_sheets:
                seen_sheets.add(sheet_name)
                matched_sheets.append(sheet_name)

    # Лист -> марка(и), которые на нём объявлены (обратный словарь к
    # brand_sheets) — один лист может быть на несколько марок сразу
    # ("Hyundai/Kia"), тогда строки помечаем первой из них: разделять один
    # физический прайс-лист на несколько идентичных копий ради тега не имеет
    # смысла, а для фильтрации в matcher._contract_candidate_pool важно лишь
    # не перепутать лист одной марки с листом другой.
    sheet_brand: dict[str, str] = {}
    for brand, sheet_name in brand_sheets.items():
        sheet_brand.setdefault(sheet_name, brand)

    results: list[dict] = []

    for matched_sheet in matched_sheets:
        ws = wb[matched_sheet]
        row_brand = sheet_brand.get(matched_sheet)
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
                    "vehicle_make": row_brand,
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
                    # Расходники общие для всех марок — не привязываем.
                    "vehicle_make": None,
                }
            )

    return results
