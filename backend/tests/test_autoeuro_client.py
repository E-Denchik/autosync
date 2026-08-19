import pytest

from app.services.autoeuro_client import AutoEuroClient, AutoEuroError


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text or str(json_data)

    def json(self):
        return self._json


def test_call_without_key_raises():
    client = AutoEuroClient(api_key="")
    with pytest.raises(AutoEuroError, match="AUTOEURO_API_KEY"):
        client.get_balance()


def test_get_balance_success(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/get_balance/k/")
        return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"balance": -100.0, "active": 1}]})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    balance = client.get_balance()
    assert balance["balance"] == -100.0


def test_call_raises_on_error_branch(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(True, {"META": {}, "ERROR": {"code": 403, "message": "Действие не разрешено"}})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    with pytest.raises(AutoEuroError, match="не разрешено"):
        client.get_balance()


def test_call_raises_on_blocked_client_state(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(True, {"META": {"client_state": "Клиент заблокирован"}, "DATA": []})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    with pytest.raises(AutoEuroError, match="заблокирован"):
        client.search_items("KYB", "333114", delivery_key="dk")


def test_search_items_uses_first_delivery_key_when_not_given(monkeypatch):
    client = AutoEuroClient(api_key="k")
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        if url.endswith("/get_deliveries/k/"):
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"delivery_key": "dk-1"}]})
        return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"brand": "KYB", "code": "333114"}]})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    client.search_items("KYB", "333114")

    search_call = [c for c in calls if "/search_items/" in c[0]][0]
    assert search_call[1]["delivery_key"] == "dk-1"


def test_find_cross_references_skips_the_exact_match(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        if "/search_brands/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"brand": "KYB", "code": "333114"}]})
        if "/get_deliveries/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"delivery_key": "dk-1"}]})
        if "/search_items/" in url:
            return _FakeResponse(
                True,
                {
                    "META": {"client_state": "OK"},
                    "DATA": [
                        {"brand": "KYB", "code": "333114", "cross": None, "price": 100},
                        {"brand": "Sachs", "code": "290074", "cross": 0, "price": 200, "name": "Амортизатор"},
                    ],
                },
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    refs = client.find_cross_references("333114")

    assert refs == [{"article": "290074", "brand": "Sachs", "name": "Амортизатор", "price": 200}]


def test_find_cross_references_returns_empty_when_brand_not_found(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": []})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    assert client.find_cross_references("unknown-article") == []


def test_search_all_with_known_brand(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        if "/get_deliveries/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"delivery_key": "dk-1"}]})
        if "/search_items/" in url:
            return _FakeResponse(
                True,
                {"META": {"client_state": "OK"}, "DATA": [{"brand": "KYB", "code": "333114", "price": 5399, "amount": 2}]},
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    items = client.search_all("333114", brand="KYB")

    assert items == [{"supplier": "autoeuro", "article": "333114", "brand": "KYB", "name": None, "price": 5399, "amount": 2}]


def test_search_all_without_brand_discovers_it(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        if "/search_brands/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"brand": "KYB", "code": "333114"}]})
        if "/get_deliveries/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"delivery_key": "dk-1"}]})
        if "/search_items/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"brand": "KYB", "code": "333114", "price": 5399}]})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    items = client.search_all("333114")

    assert items[0]["brand"] == "KYB"


def test_search_all_raises_when_search_brands_fails(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        return _FakeResponse(True, {"META": {"client_state": "Клиент заблокирован"}, "DATA": []})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    with pytest.raises(AutoEuroError, match="заблокирован"):
        client.search_all("333114")


def test_search_all_raises_when_every_candidate_brand_fails(monkeypatch):
    client = AutoEuroClient(api_key="k")

    def fake_get(url, params=None, timeout=None):
        if "/search_brands/" in url:
            return _FakeResponse(True, {"META": {"client_state": "OK"}, "DATA": [{"brand": "KYB", "code": "333114"}]})
        return _FakeResponse(True, {"META": {"client_state": "Клиент заблокирован"}, "DATA": []})

    monkeypatch.setattr("app.services.autoeuro_client.requests.get", fake_get)
    with pytest.raises(AutoEuroError, match="заблокирован"):
        client.search_all("333114")
