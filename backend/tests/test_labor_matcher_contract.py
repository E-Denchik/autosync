from unittest.mock import MagicMock

from app.extensions import db
from app.models import ConfidenceLevel, Contract, ContractLaborNorm, DocumentProcessingStatus
from app.services.labor_matcher import (
    match_all_labor_against_contract,
    match_labor_line_against_contract,
    suggest_missing_labor_operations_from_contract,
)


def _make_contract(app) -> int:
    contract = Contract(
        original_filename="c.xlsx",
        storage_path="/tmp/c.xlsx",
        status=DocumentProcessingStatus.PARSED,
    )
    db.session.add(contract)
    db.session.commit()
    return contract.id


def test_exact_operation_name_match(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id,
                operation_name="Рычаг задний подпружиненный с/у",
                vehicle_make="NISSAN",
                vehicle_model="Teana",
                norm_hours=1.3,
            )
        )
        db.session.commit()

        result = match_labor_line_against_contract(
            "Рычаг задний подпружиненный с/у", contract_id, "NISSAN", "Teana", MagicMock()
        )

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["norm_hours"] == 1.3


def test_ambiguous_operation_name_across_makes_does_not_auto_resolve_when_make_unknown(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Развал-схождение", vehicle_make="TOYOTA", norm_hours=1.0
            )
        )
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Развал-схождение", vehicle_make="KIA", norm_hours=2.5
            )
        )
        db.session.commit()

        llm_client = MagicMock()
        llm_client.match_labor_by_name.return_value = {"matched_index": None, "confidence": 0.0}

        result = match_labor_line_against_contract("Развал-схождение", contract_id, None, None, llm_client)

        assert result["confidence_level"] != ConfidenceLevel.EXACT
        llm_client.match_labor_by_name.assert_called_once()


def test_ambiguous_operation_name_resolves_exact_once_make_is_known(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Развал-схождение", vehicle_make="TOYOTA", norm_hours=1.0
            )
        )
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Развал-схождение", vehicle_make="KIA", norm_hours=2.5
            )
        )
        db.session.commit()

        result = match_labor_line_against_contract("Развал-схождение", contract_id, "KIA", None, MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["norm_hours"] == 2.5


def test_same_hours_across_makes_still_resolves_exact_without_make(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Замена масла", vehicle_make="TOYOTA", norm_hours=0.5
            )
        )
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Замена масла", vehicle_make="KIA", norm_hours=0.5
            )
        )
        db.session.commit()

        result = match_labor_line_against_contract("Замена масла", contract_id, None, None, MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["norm_hours"] == 0.5


def test_does_not_use_global_labor_catalog_only_contract(app):
    from app.models import LaborCatalogEntry

    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            LaborCatalogEntry(
                vehicle_make="NISSAN", vehicle_model="Teana", operation_name="Развал-схождение", norm_hours=1.0
            )
        )
        db.session.commit()

        llm_client = MagicMock()
        result = match_labor_line_against_contract("Развал-схождение", contract_id, "NISSAN", "Teana", llm_client)

        assert result["norm_hours"] is None
        assert result["confidence_score"] == 0.0
        llm_client.match_labor_by_name.assert_not_called()


def test_falls_back_to_llm_for_worded_differently_operation(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(
            ContractLaborNorm(
                contract_id=contract_id, operation_name="Замена масла двигателя", vehicle_make=None, norm_hours=0.5
            )
        )
        db.session.commit()

        llm_client = MagicMock()
        llm_client.match_labor_by_name.return_value = {"matched_index": 0, "confidence": 0.7}

        result = match_labor_line_against_contract("масло в двигатель поменять", contract_id, "NISSAN", None, llm_client)

        assert result["confidence_level"] == ConfidenceLevel.LLM_GUESS
        assert result["norm_hours"] == 0.5


def test_match_all_labor_against_contract(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add(ContractLaborNorm(contract_id=contract_id, operation_name="Работа A", norm_hours=2.0))
        db.session.commit()

        results = match_all_labor_against_contract(["Работа A"], contract_id, None, None, MagicMock())
        assert len(results) == 1
        assert results[0]["confidence_level"] == ConfidenceLevel.EXACT


def test_suggest_missing_labor_operations_from_contract(app):
    with app.app_context():
        contract_id = _make_contract(app)
        db.session.add_all(
            [
                ContractLaborNorm(contract_id=contract_id, operation_name="Работа A", norm_hours=1.0),
                ContractLaborNorm(contract_id=contract_id, operation_name="Работа B", norm_hours=2.0),
            ]
        )
        db.session.commit()

        matched_results = [{"matched_operation_name": "Работа A", "description": "Работа A"}]
        llm_client = MagicMock()
        llm_client.suggest_additional_labor_operations.return_value = {
            "suggestions": [{"index": 0, "confidence": 0.6, "reasoning": "обычно идёт вместе"}]
        }

        suggestions = suggest_missing_labor_operations_from_contract(
            matched_results, contract_id, None, None, llm_client
        )

        assert len(suggestions) == 1
        assert suggestions[0]["matched_operation_name"] == "Работа B"
