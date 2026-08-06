import pandas as pd
import pytest

from app.services.document_parser import DocumentParseError, parse_document

ROWS = [
    {"Артикул": "ABC-1", "Наименование": "Тормозной диск", "Кол-во": 2, "Цена": "1 500,50"},
    {"Артикул": "", "Наименование": "Фильтр масляный", "Кол-во": 1, "Цена": 350},
]


def _expected():
    return [
        {"article": "ABC-1", "name": "Тормозной диск", "qty": 2.0, "price": 1500.50},
        {"article": None, "name": "Фильтр масляный", "qty": 1.0, "price": 350.0},
    ]


def test_parse_xlsx(tmp_path):
    path = tmp_path / "contract.xlsx"
    pd.DataFrame(ROWS).to_excel(path, index=False, engine="openpyxl")
    assert parse_document(str(path)) == _expected()


def test_parse_csv_comma_utf8(tmp_path):
    path = tmp_path / "contract.csv"
    pd.DataFrame(ROWS).to_csv(path, index=False, encoding="utf-8-sig")
    assert parse_document(str(path)) == _expected()


def test_parse_csv_semicolon_cp1251(tmp_path):
    path = tmp_path / "contract.csv"
    pd.DataFrame(ROWS).to_csv(path, index=False, sep=";", encoding="cp1251")
    assert parse_document(str(path)) == _expected()


def test_parse_ods(tmp_path):
    path = tmp_path / "contract.ods"
    pd.DataFrame(ROWS).to_excel(path, index=False, engine="odf")
    assert parse_document(str(path)) == _expected()


def test_parse_docx(tmp_path):
    from docx import Document

    document = Document()
    table = document.add_table(rows=1, cols=4)
    for cell, header in zip(table.rows[0].cells, ["Артикул", "Наименование", "Кол-во", "Цена"]):
        cell.text = header
    for row_data in ROWS:
        cells = table.add_row().cells
        for cell, key in zip(cells, ["Артикул", "Наименование", "Кол-во", "Цена"]):
            cell.text = str(row_data[key])
    path = tmp_path / "order.docx"
    document.save(path)

    assert parse_document(str(path)) == _expected()


def test_unsupported_extension_raises(tmp_path):
    path = tmp_path / "contract.txt"
    path.write_text("что угодно")
    with pytest.raises(DocumentParseError):
        parse_document(str(path))
