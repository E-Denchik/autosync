from app.services.llm_client import LLMClient


class _FakeResponse:
    def __init__(self, ok, json_data):
        self.ok = ok
        self._json = json_data

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
