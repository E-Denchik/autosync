import requests

from app.services.llm_client import LLMClient, LLMClientError


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._json


def test_suggest_price_uses_dedicated_prompt_with_cost_price(app, monkeypatch):
    """Регрессия: suggest_price раньше рендерил card_generation.md (промпт
    для SEO-карточек) вместо своего — LLM не получала инструкцию учитывать
    себестоимость при рекомендации цены."""
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeResponse(True, {"text": '{"suggested_price": 1200, "reasoning": "с учётом себестоимости"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        result = client.suggest_price(
            {"name": "Тормозной диск", "sku": "SKU-1", "cost_price": 800.0},
            {"own_price": 1500, "competitor_min_price": 1400},
        )

    assert result == {"suggested_price": 1200, "reasoning": "с учётом себестоимости"}

    prompt = captured["payload"]["prompt"]
    assert "себестоимост" in prompt  # инструкция из price_suggestion.md
    assert "cost_price" in prompt
    assert "800.0" in prompt
    # card_generation.md ожидает title/bullets — suggest_price их не просит
    assert "bullets" not in prompt


def test_generate_card_content_still_uses_card_generation_prompt(app, monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(
            True,
            {"text": '{"title": "т", "bullets": [], "description": "d", "suggested_price": null, "reasoning": "r"}'},
        )

    monkeypatch.setattr("app.services.llm_client.requests.post", fake_post)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        client.generate_card_content({"name": "Товар", "sku": "SKU-1"}, [])

    assert "bullets" in captured["payload"]["prompt"]


def test_generate_retries_do_not_actually_sleep_in_testing_mode(app, monkeypatch):
    """Регрессия: TESTING=True (см. tests/conftest.py: TestConfig) обычно
    означает, что llm-service вообще не запущен — это ожидаемый мгновенный
    ConnectionError, а не "сервис перегружен", для которого задержка между
    попытками имеет смысл. Без этой проверки полный прогон тестов (десятки
    мест с незамоканным LLMClient) вырос с ~1 минуты до ~6.5 — воспроизведено
    и исправлено в этой же сессии. НЕ мокаем time.sleep — тест должен сам
    провалиться по таймауту (через реальное время), если регрессия вернётся."""
    import time as real_time

    def always_fails(url, json=None, timeout=None):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("app.services.llm_client.requests.post", always_fails)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        started = real_time.monotonic()
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError:
            pass
        elapsed = real_time.monotonic() - started

    assert elapsed < 0.5  # с реальными паузами (2с x 2 повтора) заняло бы 4+ секунды


def test_generate_retries_transient_network_error_before_succeeding(app, monkeypatch):
    """Регрессия: одиночный сетевой сбой (llm-service ещё не забиндил порт,
    модель грузится в память и т.п.) раньше сразу и безвозвратно ронял
    конкретную позицию/работу в "не найдено" — со второй попытки тот же
    сбой обычно проходит сам."""
    calls = {"n": 0}

    def flaky_post(url, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.exceptions.ConnectionError("Connection refused")
        return _FakeResponse(True, {"text": '{"suggested_price": 100, "reasoning": "ок"}'})

    monkeypatch.setattr("app.services.llm_client.requests.post", flaky_post)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        result = client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})

    assert result == {"suggested_price": 100, "reasoning": "ок"}
    assert calls["n"] == 3


def test_generate_raises_after_exhausting_all_retries(app, monkeypatch):
    calls = {"n": 0}

    def always_fails(url, json=None, timeout=None):
        calls["n"] += 1
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("app.services.llm_client.requests.post", always_fails)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: None)

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError as exc:
            assert "недоступен" in str(exc)

    assert calls["n"] == 3  # не больше и не меньше настроенного числа попыток


def test_generate_does_not_retry_on_clean_http_error_response(app, monkeypatch):
    """Ошибка вида "модель не найдена"/400 — не сетевой сбой, повтор её не
    исправит, только зря тратит время (до 3 x таймаут)."""
    calls = {"n": 0}

    def bad_response(url, json=None, timeout=None):
        calls["n"] += 1
        return _FakeResponse(False, {}, status_code=400, text="model not found")

    monkeypatch.setattr("app.services.llm_client.requests.post", bad_response)
    monkeypatch.setattr("app.services.llm_client.time.sleep", lambda *_: (_ for _ in ()).throw(AssertionError("не должно вызываться")))

    with app.app_context():
        client = LLMClient("http://llm-service:8000")
        try:
            client.suggest_price({"name": "x", "sku": "s", "cost_price": 1.0}, {})
            assert False, "expected LLMClientError"
        except LLMClientError:
            pass

    assert calls["n"] == 1
