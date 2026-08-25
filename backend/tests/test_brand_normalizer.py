from unittest.mock import MagicMock

from app.extensions import db
from app.models import BrandAlias
from app.services.brand_normalizer import normalize_brand_with_ai_fallback


def test_normalize_finds_known_alias_without_touching_llm(app):
    with app.app_context():
        llm_client = MagicMock()
        result = normalize_brand_with_ai_fallback("Шевроле", llm_client)

        assert result == "CHEVROLET"
        llm_client.normalize_brand_labels.assert_not_called()


def test_normalize_leaves_already_canonical_make_untouched(app):
    with app.app_context():
        assert normalize_brand_with_ai_fallback("HYUNDAI", None) == "HYUNDAI"


def test_normalize_falls_back_to_llm_for_unknown_brand_and_caches_result(app):
    """Заказчик: марка ОБНОВЛЕНИЕ_XYZ — заведомо нет ни в справочнике, ни в
    его дополнениях. ИИ должна была нормализовать её, и результат — попасть
    в BrandAlias, чтобы при следующей встрече с этой же меткой запрос к ИИ
    уже не понадобился."""
    with app.app_context():
        llm_client = MagicMock()
        llm_client.normalize_brand_labels.return_value = {"МАРКА_XYZ": "SOME BRAND"}

        result = normalize_brand_with_ai_fallback("МАРКА_XYZ", llm_client)
        db.session.commit()

        assert result == "SOME BRAND"
        llm_client.normalize_brand_labels.assert_called_once_with(["МАРКА_XYZ"])

        alias = BrandAlias.query.filter_by(alias="МАРКА_XYZ").first()
        assert alias is not None
        assert alias.canonical_make == "SOME BRAND"
        assert alias.source == "llm"


def test_normalize_without_llm_client_returns_dictionary_result_as_is(app):
    """Нет LLM под рукой — не должно падать, просто марка остаётся такой,
    какой её определил (или не определил) справочник."""
    with app.app_context():
        assert normalize_brand_with_ai_fallback("МАРКА_XYZ", None) == "МАРКА_XYZ"


def test_normalize_llm_failure_does_not_raise(app):
    with app.app_context():
        llm_client = MagicMock()
        llm_client.normalize_brand_labels.side_effect = RuntimeError("недоступен")

        assert normalize_brand_with_ai_fallback("МАРКА_XYZ", llm_client) == "МАРКА_XYZ"


def test_normalize_none_and_empty_pass_through(app):
    with app.app_context():
        assert normalize_brand_with_ai_fallback(None, None) is None
        assert normalize_brand_with_ai_fallback("", None) == ""
