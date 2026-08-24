import openpyxl
import pandas as pd
import pytest

from app.services.document_parser import (
    DocumentParseError,
    parse_document,
    parse_hourly_rate_table,
    parse_repair_order_export,
)

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


def _write_repair_order_export(path, labor_header: dict, labor_rows: list[dict]):
    """Строит минимальную печатную форму заказ-наряда 1С (только раздел
    "Выполненные работы") с ПРОИЗВОЛЬНЫМ порядком колонок — labor_header и
    каждая строка labor_rows задаются словарём {индекс_колонки: значение},
    индексы 0-based, как их читает pandas (см. parse_repair_order_export)."""
    wb = openpyxl.Workbook()
    ws = wb.active

    def put(row_idx: int, values: dict):
        for col0, value in values.items():
            ws.cell(row=row_idx, column=col0 + 1, value=value)

    put(1, {2: "Заказ-наряд №  0001 от 01.01.2026"})
    put(3, {2: "Выполненные работы по заказ-наряду"})
    put(5, labor_header)
    put(6, {i: str(i) for i in range(1, 9)})  # строка-легенда "1 2 3 ... 8", как в реальном файле
    row_idx = 7
    for i, data in enumerate(labor_rows, start=1):
        put(row_idx, {1: str(i), **data})
        row_idx += 1
    put(row_idx, {1: "Итого работ:"})

    wb.save(path)


STANDARD_LABOR_HEADER = {
    1: "№",
    2: "№ кат.",
    3: "Наименование",
    8: "Кол. оп.",
    9: "Цена н/ч",
    10: "Норма",
    11: "н/ч",
    12: "Всего",
}


def test_parse_repair_order_export_reads_labor_columns_by_header_not_fixed_position(tmp_path):
    path = tmp_path / "order.xlsx"
    _write_repair_order_export(
        path,
        STANDARD_LABOR_HEADER,
        [{3: "ДВС снятие", 9: 1000, 10: 28, 12: 28000}],
    )
    result = parse_repair_order_export(str(path))
    assert result["labor_lines"] == [
        {"description": "ДВС снятие", "catalog_code": None, "hourly_rate": 1000.0, "norm_hours": 28.0, "total": 28000.0}
    ]


def test_parse_repair_order_export_adapts_to_reordered_columns(tmp_path):
    """Регрессия: раньше колонки читались строго по фиксированной позиции
    (row[9]/row[10]/row[12]) — совпадало с ОДНИМ конкретным шаблоном отчёта
    1С, но другая конфигурация вполне может расставить колонки иначе.
    Здесь порядок совсем другой (наименование раньше, норма и цена
    поменяны местами, сумма в дальней колонке) — результат должен быть
    таким же, потому что колонки ищутся по заголовку, а не по индексу."""
    path = tmp_path / "order.xlsx"
    reordered_header = {
        1: "№",
        2: "Наименование работы",
        5: "№ кат.",
        9: "Норма часов",
        10: "Цена нормо-часа",
        13: "Сумма",
    }
    _write_repair_order_export(
        path,
        reordered_header,
        [{2: "ДВС снятие", 5: "K-1", 9: 28, 10: 1000, 13: 28000}],
    )
    result = parse_repair_order_export(str(path))
    assert result["labor_lines"] == [
        {"description": "ДВС снятие", "catalog_code": "K-1", "hourly_rate": 1000.0, "norm_hours": 28.0, "total": 28000.0}
    ]


def test_parse_repair_order_export_skips_labor_section_when_description_column_not_found(tmp_path):
    """Если заголовок совсем не похож на ожидаемый (колонки не нашлись) —
    раздел просто пропускается, а не заполняется мусором из случайных
    колонок (тихая порча данных хуже отсутствия данных)."""
    path = tmp_path / "order.xlsx"
    unrecognizable_header = {1: "№", 2: "Column A", 3: "Column B"}
    _write_repair_order_export(path, unrecognizable_header, [{2: "что-то", 3: "что-то ещё"}])
    result = parse_repair_order_export(str(path))
    assert result is None


def _write_repair_order_materials_export(path, materials_header: dict, materials_rows: list[dict]):
    wb = openpyxl.Workbook()
    ws = wb.active

    def put(row_idx: int, values: dict):
        for col0, value in values.items():
            ws.cell(row=row_idx, column=col0 + 1, value=value)

    put(1, {2: "Заказ-наряд №  0001 от 01.01.2026"})
    put(3, {2: "Расходная накладная к заказ-наряду"})
    put(5, materials_header)
    put(6, {i: str(i) for i in range(1, 8)})
    row_idx = 7
    for i, data in enumerate(materials_rows, start=1):
        put(row_idx, {1: str(i), **data})
        row_idx += 1
    put(row_idx, {1: "Итого материалов:"})

    wb.save(path)


def test_parse_repair_order_export_adapts_to_reordered_material_columns(tmp_path):
    path = tmp_path / "order.xlsx"
    reordered_header = {1: "№", 2: "Название", 4: "Артикул", 9: "Количество", 11: "Цена"}
    _write_repair_order_materials_export(
        path,
        reordered_header,
        [{2: "Прокладка головки блока цилиндров", 4: "2231125013", 9: 1, 11: 3100}],
    )
    result = parse_repair_order_export(str(path))
    assert result["part_lines"] == [
        {"article": "2231125013", "name": "Прокладка головки блока цилиндров", "qty": 1.0, "price": 3100.0}
    ]


def test_parse_hourly_rate_table_xlsx(tmp_path):
    path = tmp_path / "rates.xlsx"
    pd.DataFrame(
        [{"Марка": "Hyundai", "Ставка, руб/ч": 800}, {"Марка": "Toyota", "Ставка, руб/ч": 900}]
    ).to_excel(path, index=False, engine="openpyxl")
    assert parse_hourly_rate_table(str(path)) == [
        {"vehicle_make": "Hyundai", "hourly_rate": 800.0},
        {"vehicle_make": "Toyota", "hourly_rate": 900.0},
    ]


def test_parse_hourly_rate_table_adapts_to_different_column_names(tmp_path):
    """Образец файла заказчика заранее неизвестен — колонки называются как
    угодно ("Brand"/"Цена нормо-часа"), ищутся по синонимам, а не по одному
    жёстко заданному имени."""
    path = tmp_path / "rates.xlsx"
    pd.DataFrame(
        [{"Brand": "KIA", "Цена нормо-часа": "1 200,50"}]
    ).to_excel(path, index=False, engine="openpyxl")
    assert parse_hourly_rate_table(str(path)) == [{"vehicle_make": "KIA", "hourly_rate": 1200.50}]


def test_parse_hourly_rate_table_csv(tmp_path):
    path = tmp_path / "rates.csv"
    pd.DataFrame([{"Марка ТС": "Hyundai", "Стоимость": 800}]).to_csv(path, index=False, encoding="utf-8-sig")
    assert parse_hourly_rate_table(str(path)) == [{"vehicle_make": "Hyundai", "hourly_rate": 800.0}]


def test_parse_hourly_rate_table_skips_blank_make_and_non_positive_rate(tmp_path):
    path = tmp_path / "rates.xlsx"
    pd.DataFrame(
        [
            {"Марка": "Hyundai", "Ставка": 800},
            {"Марка": "", "Ставка": 900},
            {"Марка": "Toyota", "Ставка": 0},
            {"Марка": "Kia", "Ставка": -100},
        ]
    ).to_excel(path, index=False, engine="openpyxl")
    assert parse_hourly_rate_table(str(path)) == [{"vehicle_make": "Hyundai", "hourly_rate": 800.0}]


def test_parse_hourly_rate_table_raises_when_make_column_not_found(tmp_path):
    path = tmp_path / "rates.xlsx"
    pd.DataFrame([{"Column A": "x", "Ставка": 800}]).to_excel(path, index=False, engine="openpyxl")
    with pytest.raises(DocumentParseError):
        parse_hourly_rate_table(str(path))


def test_parse_hourly_rate_table_raises_when_rate_column_not_found(tmp_path):
    path = tmp_path / "rates.xlsx"
    pd.DataFrame([{"Марка": "Hyundai", "Column B": 800}]).to_excel(path, index=False, engine="openpyxl")
    with pytest.raises(DocumentParseError):
        parse_hourly_rate_table(str(path))


def test_parse_hourly_rate_table_unsupported_extension_raises(tmp_path):
    path = tmp_path / "rates.docx"
    path.write_text("что угодно")
    with pytest.raises(DocumentParseError):
        parse_hourly_rate_table(str(path))
