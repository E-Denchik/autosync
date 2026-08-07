import pandas as pd
import pytest

from app.models import NomenclatureEntry
from app.services.nomenclature_import import (
    NomenclatureImportError,
    import_nomenclature_file,
    parse_nomenclature_file,
)

ROWS = [
    {
        "Код": "PN-1",
        "№ кат.": "CAT-1",
        "Производитель": "Bosch",
        "Номенклатура": "Рычаг развальный С/У",
        "Ед.": "шт",
        "Остаток": 3,
        "Заказано": 0,
        "В резерве": 1,
        "В производстве": 0,
        "Склад": "Основной",
        "Цена": "1 250,00",
    },
    {
        "Код": "",
        "№ кат.": "",
        "Производитель": "",
        "Номенклатура": "Фильтр масляный",
        "Ед.": "шт",
        "Остаток": 10,
        "Заказано": 2,
        "В резерве": 0,
        "В производстве": 0,
        "Склад": "Основной",
        "Цена": 450,
    },
]


def _expected():
    return [
        {
            "code": "PN-1",
            "cat_number": "CAT-1",
            "manufacturer": "Bosch",
            "name": "Рычаг развальный С/У",
            "unit": "шт",
            "stock_qty": 3.0,
            "ordered_qty": 0.0,
            "reserved_qty": 1.0,
            "in_production_qty": 0.0,
            "warehouse": "Основной",
            "price": 1250.0,
        },
        {
            "code": None,
            "cat_number": None,
            "manufacturer": None,
            "name": "Фильтр масляный",
            "unit": "шт",
            "stock_qty": 10.0,
            "ordered_qty": 2.0,
            "reserved_qty": 0.0,
            "in_production_qty": 0.0,
            "warehouse": "Основной",
            "price": 450.0,
        },
    ]


def test_parse_xlsx(tmp_path):
    path = tmp_path / "nomenclature.xlsx"
    pd.DataFrame(ROWS).to_excel(path, index=False, engine="openpyxl")
    assert parse_nomenclature_file(str(path)) == _expected()


def test_parse_csv(tmp_path):
    path = tmp_path / "nomenclature.csv"
    pd.DataFrame(ROWS).to_csv(path, index=False, encoding="utf-8-sig")
    assert parse_nomenclature_file(str(path)) == _expected()


def test_unsupported_extension_raises(tmp_path):
    path = tmp_path / "nomenclature.txt"
    path.write_text("что угодно")
    with pytest.raises(NomenclatureImportError):
        parse_nomenclature_file(str(path))


def test_missing_name_column_raises(tmp_path):
    path = tmp_path / "nomenclature.xlsx"
    pd.DataFrame([{"Код": "PN-1", "Остаток": 3}]).to_excel(path, index=False, engine="openpyxl")
    with pytest.raises(NomenclatureImportError):
        parse_nomenclature_file(str(path))


def test_import_creates_and_updates_by_code(app, tmp_path):
    path = tmp_path / "nomenclature.xlsx"
    pd.DataFrame(ROWS).to_excel(path, index=False, engine="openpyxl")

    with app.app_context():
        summary = import_nomenclature_file(str(path))
        assert summary == {"rows_parsed": 2, "created": 2, "updated": 0}
        assert NomenclatureEntry.query.count() == 2

        entry = NomenclatureEntry.query.filter_by(code="PN-1").first()
        assert float(entry.stock_qty) == 3.0

        # повторная загрузка той же строки с кодом обновляет запись, а не дублирует
        # (строки без кода/№ кат. не имеют естественного ключа — каждый раз новая запись)
        updated_row = dict(ROWS[0], Остаток=7)
        path2 = tmp_path / "nomenclature2.xlsx"
        pd.DataFrame([updated_row]).to_excel(path2, index=False, engine="openpyxl")

        summary2 = import_nomenclature_file(str(path2))
        assert summary2 == {"rows_parsed": 1, "created": 0, "updated": 1}
        assert NomenclatureEntry.query.count() == 2

        entry = NomenclatureEntry.query.filter_by(code="PN-1").first()
        assert float(entry.stock_qty) == 7.0
