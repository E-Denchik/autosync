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
    monkeypatch.setattr(LLMClient, "list_models", lambda self: discovery)


def test_llm_models_requires_admin(client, operator_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.get("/api/llm/models", headers=operator_headers)
    assert resp.status_code == 403


def test_llm_models_requires_auth(client, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.get("/api/llm/models")
    assert resp.status_code == 401


def test_llm_models_no_selection_initially(client, admin_headers, monkeypatch):
    _mock_discovery(monkeypatch)
    resp = client.get("/api/llm/models", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["selected"] is None
    assert body["previous_selection"] is None
    assert body["providers"]["ollama"]["models"][0]["name"] == "llama3.2:3b"


def test_llm_service_unavailable_returns_502(client, admin_headers, monkeypatch):
    def _raise(self):
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
