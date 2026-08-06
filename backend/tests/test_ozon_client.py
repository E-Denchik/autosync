import pytest

from app.services.ozon_client import OzonClient, OzonClientError


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text or str(json_data)

    def json(self):
        return self._json


def test_seller_call_without_credentials_raises():
    client = OzonClient()
    with pytest.raises(OzonClientError, match="OZON_CLIENT_ID"):
        client.list_products()


def test_performance_call_without_credentials_raises():
    client = OzonClient(client_id="cid", api_key="key")
    with pytest.raises(OzonClientError, match="OZON_PERFORMANCE_CLIENT_ID"):
        client.list_campaigns()


def test_seller_connection_success(monkeypatch):
    client = OzonClient(client_id="cid", api_key="key")

    def fake_post(url, json=None, headers=None, timeout=None):
        assert headers["Client-Id"] == "cid"
        assert headers["Api-Key"] == "key"
        return _FakeResponse(True, {"result": {"items": [], "total": 42}})

    monkeypatch.setattr("app.services.ozon_client.requests.post", fake_post)
    message = client.test_seller_connection()
    assert "42" in message


def test_seller_connection_failure_raises(monkeypatch):
    client = OzonClient(client_id="cid", api_key="key")

    def fake_post(url, json=None, headers=None, timeout=None):
        return _FakeResponse(False, {}, status_code=401, text="Unauthorized")

    monkeypatch.setattr("app.services.ozon_client.requests.post", fake_post)
    with pytest.raises(OzonClientError, match="401"):
        client.test_seller_connection()


def test_performance_connection_success(monkeypatch):
    client = OzonClient(
        client_id="cid",
        api_key="key",
        performance_client_id="pcid",
        performance_client_secret="psecret",
    )

    def fake_post(url, json=None, timeout=None):
        assert "token" in url
        assert json["grant_type"] == "client_credentials"
        return _FakeResponse(True, {"access_token": "tok-123"})

    def fake_get(url, headers=None, timeout=None):
        assert headers["Authorization"] == "Bearer tok-123"
        return _FakeResponse(True, {"list": [{"id": 1}, {"id": 2}]})

    monkeypatch.setattr("app.services.ozon_client.requests.post", fake_post)
    monkeypatch.setattr("app.services.ozon_client.requests.get", fake_get)

    message = client.test_performance_connection()
    assert "2" in message


def test_performance_token_is_cached(monkeypatch):
    client = OzonClient(
        client_id="cid",
        api_key="key",
        performance_client_id="pcid",
        performance_client_secret="psecret",
    )

    token_calls = []

    def fake_post(url, json=None, timeout=None):
        token_calls.append(url)
        return _FakeResponse(True, {"access_token": "tok-123"})

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(True, {"list": []})

    monkeypatch.setattr("app.services.ozon_client.requests.post", fake_post)
    monkeypatch.setattr("app.services.ozon_client.requests.get", fake_get)

    client.list_campaigns()
    client.list_campaigns()
    assert len(token_calls) == 1
