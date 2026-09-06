import pytest

from app.services.model_capability import (
    capability_for_cloud_model,
    capability_for_local_model,
    guess_param_billions_from_name,
    guess_param_billions_from_size_bytes,
    parse_param_billions,
)


def test_parse_param_billions_parses_megabytes_and_billions():
    assert parse_param_billions("999.89M") == pytest.approx(0.99989)
    assert parse_param_billions("3.2B") == 3.2
    assert parse_param_billions("7B") == 7.0


def test_parse_param_billions_returns_none_for_unparseable_or_missing():
    assert parse_param_billions(None) is None
    assert parse_param_billions("") is None
    assert parse_param_billions("who knows") is None


def test_guess_param_billions_from_name_reads_trailing_size_token():
    assert guess_param_billions_from_name("llama3.2:3b") == 3.0
    assert guess_param_billions_from_name("Meta-Llama-3.1-8B-Instruct-Q4_K_M") == 8.0
    assert guess_param_billions_from_name("gemma3:1b") == 1.0


def test_guess_param_billions_from_name_avoids_false_positives():
    """Регрессия-ловушка: цифра перед буквой 'b' без явного разделителя
    размера (версия модели, часть случайного слова) не должна матчиться
    как число параметров."""
    assert guess_param_billions_from_name("model-v2-beta") is None
    assert guess_param_billions_from_name("some-model-name") is None


def test_guess_param_billions_from_size_bytes_rough_q4_heuristic():
    # ~0.6 ГБ на 1B параметров при 4-битном квантовании (см. докстринг).
    size = int(0.6 * 1024**3 * 7)
    result = guess_param_billions_from_size_bytes(size)
    assert result is not None
    assert 6.5 < result < 7.5


def test_guess_param_billions_from_size_bytes_none_for_falsy_input():
    assert guess_param_billions_from_size_bytes(None) is None
    assert guess_param_billions_from_size_bytes(0) is None


def test_capability_for_local_model_tier_boundaries():
    assert capability_for_local_model(parameter_size="1.5B", name="x")["tier"] == "tiny"
    assert capability_for_local_model(parameter_size="2B", name="x")["tier"] == "small"
    assert capability_for_local_model(parameter_size="7.9B", name="x")["tier"] == "small"
    assert capability_for_local_model(parameter_size="8B", name="x")["tier"] == "medium"
    assert capability_for_local_model(parameter_size="19.9B", name="x")["tier"] == "medium"
    assert capability_for_local_model(parameter_size="20B", name="x")["tier"] == "large"
    assert capability_for_local_model(parameter_size="70B", name="x")["tier"] == "large"


def test_capability_for_local_model_prefers_details_over_name_guess():
    """parameter_size (реальные метаданные Ollama) должен побеждать оценку
    по имени, даже если имя содержит другое число."""
    result = capability_for_local_model(parameter_size="14B", name="llama3.2:3b")
    assert result["tier"] == "medium"
    assert result["params_billions"] == 14.0
    assert result["source"] == "details"


def test_capability_for_local_model_falls_back_to_name_guess():
    result = capability_for_local_model(parameter_size=None, name="llama3.2:3b")
    assert result["params_billions"] == 3.0
    assert result["source"] == "name_guess"
    assert result["tier"] == "small"


def test_capability_for_local_model_falls_back_to_size_guess():
    size = int(0.6 * 1024**3 * 7)
    result = capability_for_local_model(parameter_size=None, name="unnamed-model", size_bytes=size)
    assert result["source"] == "size_guess"
    assert result["tier"] == "small"


def test_capability_for_local_model_unknown_when_nothing_available():
    result = capability_for_local_model(parameter_size=None, name="unnamed-model", size_bytes=None)
    assert result["tier"] == "unknown"
    assert result["label"] is None
    assert result["note"]


def test_capability_for_cloud_model_is_fixed_note_regardless_of_name():
    a = capability_for_cloud_model("openai/gpt-4o-mini")
    b = capability_for_cloud_model("openai/o3")
    assert a["tier"] == "cloud" == b["tier"]
    assert a["note"] == b["note"]
