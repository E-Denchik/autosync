from app.services.llm_client import LLMClient, LLMClientError

DISCOVERY = {
    "providers": {
        "ollama": {
            "available": True,
            "models": [{"name": "llama3.2:3b"}, {"name": "gemma3:1b"}],
        },
        "lmstudio": {"available": False, "server_running": False, "models": []},
    }
}


def _mock_discovery(monkeypatch, discovery=DISCOVERY):
    monkeypatch.setattr(LLMClient, "list_models", lambda self, vsegpt_api_key=None: discovery)


def test_llm_models_no_selection_initially(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.get("/api/llm/models", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["selected"] is None
    assert body["previous_selection"] is None
    assert body["providers"]["ollama"]["models"][0]["name"] == "llama3.2:3b"


def test_llm_service_unavailable_returns_502(client, admin_headers, monkeypatch):
    def _raise(self, vsegpt_api_key=None):
        raise LLMClientError("connection refused")

    monkeypatch.setattr(LLMClient, "list_models", _raise)
    resp = client.get("/api/llm/models", headers=admin_headers)
    assert resp.status_code == 502


def test_select_unknown_model_rejected(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.post(
        "/api/llm/select",
        headers=admin_headers,
        json={"provider": "ollama", "model": "does-not-exist:9b"},
    )
    assert resp.status_code == 404


def test_select_invalid_provider_rejected(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.post(
        "/api/llm/select", headers=admin_headers, json={"provider": "chatgpt", "model": "x"}
    )
    assert resp.status_code == 400


def test_select_persists_and_shows_in_models(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    select_resp = client.post(
        "/api/llm/select",
        headers=admin_headers,
        json={"provider": "ollama", "model": "llama3.2:3b"},
    )
    assert select_resp.status_code == 200

    models_resp = client.get("/api/llm/models", headers=admin_headers)
    assert models_resp.get_json()["selected"] == {"provider": "ollama", "model": "llama3.2:3b"}


def test_selection_cleared_when_model_disappears_from_discovery(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    client.post(
        "/api/llm/select",
        headers=admin_headers,
        json={"provider": "ollama", "model": "llama3.2:3b"},
    )

    # модель "удалили с диска" — теперь discovery её не видит
    smaller_discovery = {
        "providers": {
            "ollama": {"available": True, "models": [{"name": "gemma3:1b"}]},
            "lmstudio": {"available": False, "server_running": False, "models": []},
        }
    }
    _mock_discovery(monkeypatch, smaller_discovery)

    resp = client.get("/api/llm/models", headers=admin_headers)
    body = resp.get_json()
    assert body["selected"] is None
    assert body["previous_selection"] == {"provider": "ollama", "model": "llama3.2:3b"}

    # выбор реально сброшен в БД, не просто "скрыт" в одном ответе
    resp2 = client.get("/api/llm/models", headers=admin_headers)
    assert resp2.get_json()["previous_selection"] is None


def test_llm_test_endpoint_reports_success_when_model_responds(client, admin_headers, monkeypatch):
    """Регрессия: модель может числиться на диске (list_models её видит), но
    не влезать в доступную память при реальной загрузке — /models этого не
    ловит. /test делает настоящий пробный запрос и дожидается ответа
    (см. LLMClient.test_connection), чтобы UploadPage.jsx мог предупредить
    об этом ДО загрузки файлов, а не посреди обработки заказ-наряда."""
    monkeypatch.setattr(LLMClient, "test_connection", lambda self: "Модель отвечает, можно продолжать.")
    resp = client.post("/api/llm/test", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "отвечает" in body["message"]


def test_vsegpt_configured_false_by_default(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.get("/api/llm/models", headers=admin_headers)
    assert resp.get_json()["vsegpt_configured"] is False


def test_vsegpt_configured_true_after_saving_key(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    save_resp = client.post(
        "/api/integrations/keys", headers=admin_headers, json={"VSEGPT_API_KEY": "sk-test"}
    )
    assert save_resp.status_code == 200

    resp = client.get("/api/llm/models", headers=admin_headers)
    assert resp.get_json()["vsegpt_configured"] is True


def test_list_models_passes_vsegpt_key_to_client(client, admin_headers, monkeypatch):
    """Regression: без ключа llm-service не должен даже пытаться идти на
    vsegpt.ru (см. discover_vsegpt в llm-service/server.py) — backend обязан
    передавать сохранённый ключ с каждым вызовом list_models."""
    captured = {}

    def fake_list_models(self, vsegpt_api_key=None):
        captured["vsegpt_api_key"] = vsegpt_api_key
        return DISCOVERY

    monkeypatch.setattr(LLMClient, "list_models", fake_list_models)
    client.post("/api/integrations/keys", headers=admin_headers, json={"VSEGPT_API_KEY": "sk-test"})
    client.get("/api/llm/models", headers=admin_headers)

    assert captured["vsegpt_api_key"] == "sk-test"


def test_select_vsegpt_model_allowed(client, admin_headers, monkeypatch):
    discovery_with_vsegpt = {
        "providers": {
            **DISCOVERY["providers"],
            "vsegpt": {"available": True, "models": [{"name": "openai/gpt-4o-mini"}]},
        }
    }
    _mock_discovery(monkeypatch, discovery_with_vsegpt)

    resp = client.post(
        "/api/llm/select",
        headers=admin_headers,
        json={"provider": "vsegpt", "model": "openai/gpt-4o-mini"},
    )
    assert resp.status_code == 200

    models_resp = client.get("/api/llm/models", headers=admin_headers)
    assert models_resp.get_json()["selected"] == {"provider": "vsegpt", "model": "openai/gpt-4o-mini"}


def test_llm_test_endpoint_reports_failure_without_500(client, admin_headers, monkeypatch):
    """Реальный сценарий заказчика: модель выбрана, но раннер падает с
    нехваткой памяти при загрузке — эндпоинт должен вернуть понятную
    причину с кодом 200 (ok: false), а не голый 500."""

    def _raise(self):
        raise LLMClientError(
            "llm-service -> 502: {\"error\":\"ollama -> 500: ...out-of-memory during startup...\"}"
        )

    monkeypatch.setattr(LLMClient, "test_connection", _raise)
    resp = client.post("/api/llm/test", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "out-of-memory" in body["error"]
