from unittest.mock import MagicMock

from app.models import ConfidenceLevel
from app.services.matcher import match_line


def test_exact_article_match_wins_without_calling_supplier_or_llm():
    contract_line = {"article": "ABC-123", "name": "Тормозной диск"}
    order_lines = [{"article": "ABC-123", "name": "Диск тормозной", "price": 1500.0}]

    supplier_client = MagicMock()
    llm_client = MagicMock()

    result = match_line(contract_line, order_lines, supplier_client, llm_client)

    assert result["confidence_level"] == ConfidenceLevel.EXACT
    assert result["matched_price"] == 1500.0
    supplier_client.find_cross_references.assert_not_called()
    llm_client.match_part_by_name.assert_not_called()


def test_falls_back_to_cross_reference_when_no_exact_match():
    contract_line = {"article": "XYZ-999", "name": "Фильтр масляный"}
    order_lines = [{"article": "OTHER-1", "name": "Что-то другое", "price": 100.0}]

    supplier_client = MagicMock()
    supplier_client.find_cross_references.return_value = [
        {"article": "CROSS-1", "name": "Аналог фильтра", "price": 350.0}
    ]
    llm_client = MagicMock()

    result = match_line(contract_line, order_lines, supplier_client, llm_client)

    assert result["confidence_level"] == ConfidenceLevel.CROSS_REF
    assert result["matched_article"] == "CROSS-1"
    llm_client.match_part_by_name.assert_not_called()


def test_falls_back_to_llm_when_no_article_or_cross_ref():
    contract_line = {"article": None, "name": "Свеча зажигания NGK"}
    order_lines = [{"article": "SP-1", "name": "Свеча NGK BKR6E", "price": 250.0}]

    supplier_client = MagicMock()
    llm_client = MagicMock()
    llm_client.match_part_by_name.return_value = {
        "matched_index": 0,
        "confidence": 0.8,
        "reasoning": "совпадение по бренду и типу",
    }

    result = match_line(contract_line, order_lines, supplier_client, llm_client)

    assert result["confidence_level"] == ConfidenceLevel.LLM_GUESS
    assert result["matched_article"] == "SP-1"
    assert result["confidence_score"] == 0.8
