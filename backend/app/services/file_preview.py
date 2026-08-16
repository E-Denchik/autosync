from __future__ import annotations

import os

import pandas as pd

MAX_PREVIEW_ROWS = 200
TABLE_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"}


class FilePreviewError(RuntimeError):
    pass


def _rows_from_dataframe(df: pd.DataFrame) -> dict:
    total = len(df)
    head = df.head(MAX_PREVIEW_ROWS)
    header = [("" if str(c).startswith("Unnamed") else str(c)) for c in head.columns]
    rows = [header]
    for _, row in head.iterrows():
        rows.append(["" if pd.isna(v) else str(v) for v in row.tolist()])
    return {"rows": rows, "truncated": total > MAX_PREVIEW_ROWS}


def preview_table(file_path: str) -> dict:
    ext = os.path.splitext(file_path)[1].lower()
    try:
        if ext in (".xlsx", ".xlsm"):
            df = pd.read_excel(file_path, engine="openpyxl", dtype=str)
        elif ext == ".xls":
            df = pd.read_excel(file_path, engine="xlrd", dtype=str)
        elif ext == ".ods":
            df = pd.read_excel(file_path, engine="odf", dtype=str)
        elif ext == ".csv":
            df = None
            last_error: Exception | None = None
            for encoding in ("utf-8-sig", "cp1251"):
                try:
                    df = pd.read_csv(file_path, sep=None, engine="python", encoding=encoding, dtype=str)
                    break
                except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                    last_error = exc
            if df is None:
                raise FilePreviewError(f"Не удалось прочитать CSV (кодировка/разделитель): {last_error}")
        elif ext == ".docx":
            from app.services.document_parser import extract_docx_tables

            tables = extract_docx_tables(file_path)
            if not tables:
                raise FilePreviewError("В файле не найдено таблиц")
            df = tables[0]
        elif ext == ".pdf":
            from app.services.document_parser import extract_pdf_tables

            tables = extract_pdf_tables(file_path)
            if not tables:
                raise FilePreviewError("В файле не найдено таблиц (возможно, это скан — предпросмотр недоступен)")
            df = tables[0]
        else:
            raise FilePreviewError(f"Предпросмотр не поддерживается для {ext}")
    except FilePreviewError:
        raise
    except Exception as exc:
        raise FilePreviewError(f"Не удалось прочитать файл: {exc}") from exc

    return _rows_from_dataframe(df)
