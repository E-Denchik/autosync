from app.extensions import db
from app.models import NomenclatureEntry
from app.services.nomenclature_client import NomenclatureClient


def _add_entry(**kwargs):
    entry = NomenclatureEntry(**kwargs)
    db.session.add(entry)
    db.session.commit()
    return entry


def test_find_match_by_exact_code(app):
    with app.app_context():
        _add_entry(code="PN-1", name="Рычаг развальный С/У", stock_qty=3, warehouse="Основной")

        client = NomenclatureClient(base_url="", api_key="")
        result = client.find_match("PN-1", "что угодно")

        assert result["code"] == "PN-1"
        assert result["stock_qty"] == 3.0
        assert result["match_source"] == "code"


def test_find_match_by_cat_number_when_code_differs(app):
    with app.app_context():
        _add_entry(cat_number="CAT-1", name="Фильтр масляный", stock_qty=10)

        client = NomenclatureClient(base_url="", api_key="")
        result = client.find_match("CAT-1", None)

        assert result["cat_number"] == "CAT-1"
        assert result["match_source"] == "code"


def test_find_match_falls_back_to_fuzzy_name(app):
    with app.app_context():
        _add_entry(code="PN-9", name="Рычаг развальный С/У", stock_qty=5)

        client = NomenclatureClient(base_url="", api_key="")
        result = client.find_match(None, "Рычаг развальный СУ")

        assert result is not None
        assert result["code"] == "PN-9"
        assert result["match_source"] == "fuzzy_name"


def test_find_match_returns_none_when_nothing_close(app):
    with app.app_context():
        _add_entry(code="PN-1", name="Рычаг развальный С/У")

        client = NomenclatureClient(base_url="", api_key="")
        result = client.find_match("OTHER-CODE", "Совершенно другая деталь XYZ")

        assert result is None


def test_find_match_returns_none_on_empty_catalog(app):
    with app.app_context():
        client = NomenclatureClient(base_url="", api_key="")
        assert client.find_match("ANY", "Что угодно") is None
