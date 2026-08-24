from unittest.mock import MagicMock

from app.extensions import db
from app.models import ConfidenceLevel, Contract, ContractPart, DocumentProcessingStatus
from app.services.matcher import match_all_against_contract, match_line_against_contract


def _make_contract(app) -> int:
    contract = Contract(
        original_filename="c.xlsx",
        storage_path="/tmp/c.xlsx",
        status=DocumentProcessingStatus.PARSED,
    )
    db.session.add(contract)
    db.session.commit()
    return contract.id


def test_exact_article_match_uses_contract_price_not_order_price(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractPart(contract_id=contract_id, article="ABC-123", name="Диск тормозной", price=1500.0))
        db.session.commit()

        order_line = {"article": "ABC-123", "name": "диск тормоз задний", "price": 999.0}
        result = match_line_against_contract(order_line, contract_id, MagicMock(), MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["matched_article"] == "ABC-123"
        assert result["matched_name"] == "Диск тормозной"
        assert float(result["matched_price"]) == 1500.0
        assert result["contract_article"] == "ABC-123"
        assert result["contract_name"] == "диск тормоз задний"


def test_exact_match_strips_bracketed_brand_from_article(app):
    """Регрессия: выгрузка заказ-наряда из 1С кладёт бренд прямо в артикул
    ("PN32661 [AUTOWELT]") — раньше это сравнивалось с ContractPart.article
    буквально и почти никогда не совпадало, хотя чистый код в договоре есть."""
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractPart(contract_id=contract_id, article="PN32661", name="Поршень", price=2500.0))
        db.session.commit()

        order_line = {"article": "PN32661 [AUTOWELT]", "name": "PN32661 поршень с кольцами"}
        result = match_line_against_contract(order_line, contract_id, MagicMock(), MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["matched_article"] == "PN32661"
        # Отображаемое поле — оригинальная строка из документа, не обрезанная.
        assert result["contract_article"] == "PN32661 [AUTOWELT]"


def test_cross_reference_lookup_uses_clean_article_and_extracted_brand(app):
    with app.app_context():
        contract_id = _make_contract(app)
        supplier_client = MagicMock()
        supplier_client.find_cross_references.return_value = []
        llm_client = MagicMock()
        llm_client.match_part_by_name.return_value = None

        order_line = {"article": "141038301 [REINZ]", "name": "Комплект болтов головки цилиндра"}
        match_line_against_contract(order_line, contract_id, supplier_client, llm_client)

        supplier_client.find_cross_references.assert_called_once_with("141038301", brand="REINZ")


def test_no_article_match_falls_back_to_cross_reference(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractPart(contract_id=contract_id, article="CROSS-1", name="Аналог фильтра", price=350.0))
        db.session.commit()

        supplier_client = MagicMock()
        supplier_client.find_cross_references.return_value = [{"article": "CROSS-1", "name": "x", "price": 1}]
        llm_client = MagicMock()

        order_line = {"article": "XYZ-999", "name": "Фильтр масляный"}
        result = match_line_against_contract(order_line, contract_id, supplier_client, llm_client)

        assert result["confidence_level"] == ConfidenceLevel.CROSS_REF
        assert result["matched_article"] == "CROSS-1"
        assert float(result["matched_price"]) == 350.0
        llm_client.match_part_by_name.assert_not_called()


def test_falls_back_to_llm_when_no_exact_or_cross_ref(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractPart(contract_id=contract_id, article="SP-1", name="Свеча NGK BKR6E", price=250.0))
        db.session.commit()

        supplier_client = MagicMock()
        supplier_client.find_cross_references.return_value = []
        llm_client = MagicMock()
        llm_client.match_part_by_name.return_value = {"matched_index": 0, "confidence": 0.8, "reasoning": "совпадение"}

        order_line = {"article": None, "name": "Свеча зажигания NGK"}
        result = match_line_against_contract(order_line, contract_id, supplier_client, llm_client)

        assert result["confidence_level"] == ConfidenceLevel.LLM_GUESS
        assert result["matched_article"] == "SP-1"
        assert result["confidence_score"] == 0.8


def test_returns_no_match_when_contract_catalog_is_empty(app):
    with app.app_context():
        contract_id = _make_contract(app)

        order_line = {"article": "ANY", "name": "Что угодно"}
        result = match_line_against_contract(order_line, contract_id, MagicMock(), MagicMock())

        assert result["matched_article"] is None
        assert result["confidence_score"] == 0.0


def test_exact_match_ignores_dashes_and_spaces_in_article(app):
    """Регрессия по реальным данным заказчика: заказ-наряд, набитый механиком
    в Excel, содержит артикул без тире ("234102G000"), а каталог договора —
    в каноническом формате поставщика с тире ("234102-G000" /
    "23410-2G000") — это тот же физический артикул, просто другое
    форматирование, не другая деталь."""
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractPart(contract_id=contract_id, article="23410-2G000", name="Поршень двигателя с пальцем", price=3123.80)
        )
        db.session.commit()

        order_line = {"article": "234102G000", "name": "ПОРШЕНЬ ДВИГАТЕЛЯ С ПАЛЬЦЕМ"}
        result = match_line_against_contract(order_line, contract_id, MagicMock(), MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["matched_article"] == "23410-2G000"
        assert float(result["matched_price"]) == 3123.80
        assert result["raw_match_data"]["source"] == "exact_article_match_normalized"


def test_exact_match_ignores_extra_spaces_in_article(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractPart(contract_id=contract_id, article="ABC 123 45", name="Деталь", price=100.0))
        db.session.commit()

        order_line = {"article": "ABC12345", "name": "деталь"}
        result = match_line_against_contract(order_line, contract_id, MagicMock(), MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["matched_article"] == "ABC 123 45"


def test_byte_exact_match_still_preferred_over_normalized_when_both_exist(app):
    """Если в каталоге есть И буквально точный артикул, И другая строка с тем
    же нормализованным видом — точное совпадение должно побеждать, чтобы не
    подменять явно указанный артикул похожим по форме."""
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractPart(contract_id=contract_id, article="234102G000", name="Деталь А (точная)", price=1.0))
        db.session.add(ContractPart(contract_id=contract_id, article="23410-2G000", name="Деталь Б (нормализованная)", price=2.0))
        db.session.commit()

        order_line = {"article": "234102G000", "name": "деталь"}
        result = match_line_against_contract(order_line, contract_id, MagicMock(), MagicMock())

        assert result["matched_article"] == "234102G000"
        assert result["raw_match_data"]["source"] == "exact_article_match"


def test_cross_reference_result_matched_against_catalog_ignoring_dashes(app):
    """Полная регрессия по скриншотам заказчика: заказ-наряд содержит
    "PN32661 [AUTOWELT]" (аналог), поставщик по кросс-номеру отдаёт
    официальный код Hyundai/Kia "23410-2G000" (с тире), а в каталоге
    договора этот же артикул записан без тире ("234102G000") — раньше
    verification-запрос сравнивал их буквально и терял совпадение."""
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractPart(contract_id=contract_id, article="234102G000", name="Поршень двигателя с пальцем", price=3123.80)
        )
        db.session.commit()

        supplier_client = MagicMock()
        supplier_client.find_cross_references.return_value = [
            {"article": "23410-2G000", "name": "Поршень двигателя с поршневым пальцем", "price": 3123.80}
        ]
        llm_client = MagicMock()

        order_line = {"article": "PN32661 [AUTOWELT]", "name": "PN32661 поршень с кольцами 0.50 HYUNDAI/KIA G4KD *AUTOWELT"}
        result = match_line_against_contract(order_line, contract_id, supplier_client, llm_client)

        assert result["confidence_level"] == ConfidenceLevel.CROSS_REF
        assert result["matched_article"] == "234102G000"
        assert float(result["matched_price"]) == 3123.80
        llm_client.match_part_by_name.assert_not_called()


def test_match_all_against_contract_scales_to_many_parts(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.bulk_insert_mappings(
            ContractPart,
            [
                {"contract_id": contract_id, "article": f"ART-{i}", "name": f"Деталь {i}", "price": float(i)}
                for i in range(2000)
            ],
        )
        db.session.commit()

        order_lines = [{"article": "ART-1500", "name": "деталь 1500"}, {"article": "ART-3", "name": "деталь 3"}]
        results = match_all_against_contract(order_lines, contract_id, MagicMock(), MagicMock())

        assert len(results) == 2
        assert all(r["confidence_level"] == ConfidenceLevel.EXACT for r in results)
        assert float(results[0]["matched_price"]) == 1500.0
        assert float(results[1]["matched_price"]) == 3.0
