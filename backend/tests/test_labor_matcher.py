from unittest.mock import MagicMock

from app.extensions import db
from app.models import ConfidenceLevel, LaborCatalogEntry
from app.services.autodata_client import AutoDataClient
from app.services.labor_matcher import match_labor_line


def _local_client() -> AutoDataClient:
    return AutoDataClient(base_url="")  # без 1С — работает по локальному справочнику


def test_exact_operation_name_match(app):
    with app.app_context():
        db.session.add(
            LaborCatalogEntry(vehicle_make="KIA", vehicle_model="Rio", operation_name="Замена масла", norm_hours=0.5)
        )
        db.session.commit()

        result = match_labor_line("Замена масла", "KIA", "Rio", _local_client(), MagicMock())

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["norm_hours"] == 0.5


def test_operation_with_different_word_order_uses_exact_match(app):
    with app.app_context():
        db.session.add(
            LaborCatalogEntry(
                vehicle_make="KIA",
                operation_name="Снятие установка защиты двигателя",
                norm_hours=0.8,
            )
        )
        db.session.commit()

        result = match_labor_line(
            "Защиты двигателя установка снятие",
            "KIA",
            "Rio",
            _local_client(),
            MagicMock(),
        )

        assert result["confidence_level"] == ConfidenceLevel.EXACT
        assert result["norm_hours"] == 0.8


def test_falls_back_to_llm_for_worded_differently_operation(app):
    with app.app_context():
        db.session.add(
            LaborCatalogEntry(vehicle_make="KIA", operation_name="Замена масла двигателя", norm_hours=0.5)
        )
        db.session.commit()

        llm_client = MagicMock()
        llm_client.match_labor_by_name.return_value = {"matched_index": 0, "confidence": 0.7}

        result = match_labor_line("масло в двигатель поменять", "KIA", "Rio", _local_client(), llm_client)

        assert result["confidence_level"] == ConfidenceLevel.LLM_GUESS
        assert result["norm_hours"] == 0.5
        assert result["raw_match_data"]["source"] == "llm_fallback"


def test_no_entries_for_make_at_all_still_tries_llm_with_other_makes(app):
    """Регрессия: если в справочнике вообще нет ни одной записи для точной
    марки заказ-наряда (обычная ситуация для бизнеса, который только начал
    вести свой справочник, без 1С/AutoData) — раньше LLM даже не звали, и
    работа сразу уходила в "не найдено", хотя многие операции (замена
    масла и т.п.) по факту не зависят от марки."""
    with app.app_context():
        db.session.add(
            LaborCatalogEntry(vehicle_make="TOYOTA", operation_name="Замена масла в двигателе", norm_hours=0.5)
        )
        db.session.commit()

        llm_client = MagicMock()
        llm_client.match_labor_by_name.return_value = {"matched_index": 0, "confidence": 0.55}

        # Заказ-наряд — KIA, в справочнике есть только TOYOTA.
        result = match_labor_line("Замена масла в двигателе", "KIA", "Rio", _local_client(), llm_client)

        llm_client.match_labor_by_name.assert_called_once()
        called_kwargs = llm_client.match_labor_by_name.call_args.kwargs
        assert called_kwargs["vehicle_make"] == "KIA"
        candidates_arg = llm_client.match_labor_by_name.call_args.args[1]
        assert any(c["vehicle_make"] == "TOYOTA" for c in candidates_arg)

        assert result["confidence_level"] == ConfidenceLevel.LLM_GUESS
        assert result["norm_hours"] == 0.5
        assert result["raw_match_data"]["source"] == "llm_fallback_cross_make"
        assert result["confidence_score"] <= 0.6


def test_no_entries_at_all_still_reports_no_match_found_not_crash(app):
    with app.app_context():
        result = match_labor_line("Замена масла", "KIA", "Rio", _local_client(), MagicMock())

        assert result["norm_hours"] is None
        assert result["raw_match_data"]["source"] == "no_match_found"
