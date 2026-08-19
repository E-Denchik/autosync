import pytest

from app.services.moskvorechye_client import MoskvorechyeClient, MoskvorechyeError


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text or str(json_data)

    def json(self):
        return self._json


def test_search_without_base_url_raises():
    client = MoskvorechyeClient(base_url="", api_key="login:pass")
    with pytest.raises(MoskvorechyeError, match="MOSKVORECHYE_BASE_URL"):
        client.search_articles("333114")


def test_search_with_malformed_key_raises():
    client = MoskvorechyeClient(base_url="https://example.abcp2b.ru", api_key="no-colon-here")
    with pytest.raises(MoskvorechyeError, match="login:password"):
        client.search_articles("333114")


def test_search_articles_splits_login_password_and_sends_them(monkeypatch):
    client = MoskvorechyeClient(base_url="https://example.abcp2b.ru", api_key="JjDAUI1jnzWX:50mKreI7N24uoZyA")
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(True, [{"brand": "KYB", "articleCode": "333114", "price": 5399}])

    monkeypatch.setattr("app.services.moskvorechye_client.requests.get", fake_get)
    items = client.search_articles("333114")

    assert captured["url"] == "https://example.abcp2b.ru/search/articles/"
    assert captured["params"]["userlogin"] == "JjDAUI1jnzWX"
    assert captured["params"]["userpsw"] == "50mKreI7N24uoZyA"
    assert captured["params"]["number"] == "333114"
    assert items[0]["price"] == 5399


def test_find_cross_references_maps_fields(monkeypatch):
    client = MoskvorechyeClient(base_url="https://example.abcp2b.ru", api_key="login:pass")

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(
            True,
            [{"articleCodeFix": "333114", "brand": "KYB", "description": "Стойка амортизационная", "price": 5399}],
        )

    monkeypatch.setattr("app.services.moskvorechye_client.requests.get", fake_get)
    refs = client.find_cross_references("333114")

    assert refs == [{"article": "333114", "brand": "KYB", "name": "Стойка амортизационная", "price": 5399}]


def test_find_cross_references_returns_empty_on_error(monkeypatch):
    client = MoskvorechyeClient(base_url="https://example.abcp2b.ru", api_key="login:pass")

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(False, {}, status_code=500, text="server error")

    monkeypatch.setattr("app.services.moskvorechye_client.requests.get", fake_get)
    assert client.find_cross_references("333114") == []
