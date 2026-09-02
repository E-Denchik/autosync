from unittest.mock import MagicMock

from app.services.nomenclature_client import NomenclatureClientError
from app.services.nomenclature_matcher import enrich_all, enrich_part_match


def test_enrich_part_match_merges_found_fields():
    match = {"matched_article": "PN-1", "matched_name": "Рычаг развальный С/У", "matched_price": 500.0}
    client = MagicMock()
    client.find_match.return_value = {
        "code": "PN-1",
        "cat_number": "CAT-1",
        "manufacturer": "Bosch",
        "name": "Рычаг развальный С/У",
        "unit": "шт",
        "stock_qty": 3.0,
        "reserved_qty": 1.0,
        "in_production_qty": 0.0,
        "ordered_qty": 0.0,
        "warehouse": "Основной",
        "match_source": "code",
    }

    result = enrich_part_match(match, client)

    assert result["matched_price"] == 500.0  # исходные поля не трогаем
    assert result["nomenclature_code"] == "PN-1"
    assert result["nomenclature_cat_number"] == "CAT-1"
    assert result["nomenclature_stock_qty"] == 3.0
    assert result["nomenclature_warehouse"] == "Основной"
    assert result["nomenclature_source"] == "code"
    client.find_match.assert_called_once_with("PN-1", "Рычаг развальный С/У")


def test_enrich_part_match_no_match_leaves_fields_none():
    match = {"matched_article": "PN-1", "matched_name": "Что-то"}
    client = MagicMock()
    client.find_match.return_value = None

    result = enrich_part_match(match, client)

    assert result["nomenclature_code"] is None
    assert result["nomenclature_source"] is None


def test_enrich_part_match_skips_lookup_without_article_or_name():
    match = {"matched_article": None, "matched_name": None, "contract_article": None, "contract_name": None}
    client = MagicMock()

    result = enrich_part_match(match, client)

    client.find_match.assert_not_called()
    assert result["nomenclature_code"] is None


def test_enrich_part_match_survives_client_error():
    match = {"matched_article": "PN-1", "matched_name": "Деталь"}
    client = MagicMock()
    client.find_match.side_effect = NomenclatureClientError("недоступен")

    result = enrich_part_match(match, client)

    assert result["nomenclature_code"] is None
    assert result["nomenclature_source"] is None


def test_enrich_all_preserves_order_and_count(app):
    """enrich_all теперь обогащает позиции параллельно (см.
    services/parallel.py: map_with_app_context) — на >1 элементе это
    реальные потоки, каждому нужен свой Flask app_context, поэтому тест
    (в отличие от enrich_part_match напрямую) требует app-фикстуру."""
    matches = [
        {"matched_article": "A", "matched_name": "Деталь A"},
        {"matched_article": "B", "matched_name": "Деталь B"},
    ]
    client = MagicMock()
    client.find_match.return_value = None

    with app.app_context():
        result = enrich_all(matches, client)

    assert len(result) == 2
    assert client.find_match.call_count == 2
