import pytest

from app.extensions import db
from app.models import LaborCatalogEntry
from app.services.autodata_client import AutoDataClient, AutoDataError


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text or str(json_data)

    def json(self):
        return self._json


def _add_entry(**kwargs):
    entry = LaborCatalogEntry(source="manual", **kwargs)
    db.session.add(entry)
    db.session.commit()
    return entry


# ---------- локальный режим (без base_url) ----------


def test_find_norm_hours_local_matches_by_make_case_insensitively(app):
    with app.app_context():
        _add_entry(vehicle_make="KIA", vehicle_model="Rio", operation_name="Замена масла", norm_hours=1)

        client = AutoDataClient(base_url="")
        results = client.find_norm_hours("kia", "Rio")

        assert results == [
            {"operation_name": "Замена масла", "norm_hours": 1.0, "vehicle_make": "KIA", "vehicle_model": "Rio"}
        ]


def test_find_norm_hours_local_includes_make_wide_entries_regardless_of_model(app):
    with app.app_context():
        _add_entry(vehicle_make="KIA", vehicle_model=None, operation_name="Общая для всех KIA", norm_hours=2)
        _add_entry(vehicle_make="KIA", vehicle_model="Sportage", operation_name="Только для Sportage", norm_hours=3)

        client = AutoDataClient(base_url="")
        results = client.find_norm_hours("KIA", "Rio")

        names = {r["operation_name"] for r in results}
        assert names == {"Общая для всех KIA"}


def test_find_norm_hours_local_without_model_returns_all_makes_entries(app):
    with app.app_context():
        _add_entry(vehicle_make="KIA", vehicle_model=None, operation_name="A", norm_hours=1)
        _add_entry(vehicle_make="KIA", vehicle_model="Sportage", operation_name="B", norm_hours=2)

        client = AutoDataClient(base_url="")
        results = client.find_norm_hours("KIA", None)

        assert {r["operation_name"] for r in results} == {"A", "B"}


def test_find_norm_hours_local_empty_catalog_returns_empty_list(app):
    with app.app_context():
        client = AutoDataClient(base_url="")
        assert client.find_norm_hours("KIA", "Rio") == []


def test_test_connection_local_reports_catalog_count(app):
    with app.app_context():
        _add_entry(vehicle_make="KIA", operation_name="A", norm_hours=1)
        _add_entry(vehicle_make="HYUNDAI", operation_name="B", norm_hours=1)

        client = AutoDataClient(base_url="")
        message = client.test_connection()

        assert "2 записей" in message
        assert "не подключена" in message


# ---------- удалённый режим (1С OData) ----------


def test_auth_is_none_without_login():
    client = AutoDataClient(base_url="http://1c.local/odata", login="", password="")
    assert client._auth() is None


def test_auth_is_tuple_with_login():
    client = AutoDataClient(base_url="http://1c.local/odata", login="user", password="pass")
    assert client._auth() == ("user", "pass")


def test_find_norm_hours_remote_builds_odata_filter_and_sends_auth(monkeypatch):
    client = AutoDataClient(base_url="http://1c.local/odata", login="user", password="pass")
    captured = {}

    def fake_get(url, params=None, headers=None, auth=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["auth"] = auth
        return _FakeResponse(True, {"value": [{"operation_name": "Замена масла", "norm_hours": 1}]})

    monkeypatch.setattr("app.services.autodata_client.requests.get", fake_get)
    results = client.find_norm_hours("KIA", "Rio")

    assert captured["url"] == "http://1c.local/odata/Catalog_НормыВремени"
    assert captured["auth"] == ("user", "pass")
    assert "МаркаТС eq 'KIA'" in captured["params"]["$filter"]
    assert "МодельТС eq 'Rio'" in captured["params"]["$filter"]
    assert results == [{"operation_name": "Замена масла", "norm_hours": 1}]


def test_find_norm_hours_remote_omits_model_filter_when_not_given(monkeypatch):
    client = AutoDataClient(base_url="http://1c.local/odata")
    captured = {}

    def fake_get(url, params=None, headers=None, auth=None, timeout=None):
        captured["params"] = params
        return _FakeResponse(True, {"value": []})

    monkeypatch.setattr("app.services.autodata_client.requests.get", fake_get)
    client.find_norm_hours("KIA", None)

    assert captured["params"]["$filter"] == "МаркаТС eq 'KIA'"


def test_find_norm_hours_remote_raises_on_network_error(monkeypatch):
    import requests

    client = AutoDataClient(base_url="http://1c.local/odata")

    def fake_get(*a, **kw):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr("app.services.autodata_client.requests.get", fake_get)
    with pytest.raises(AutoDataError, match="недоступен"):
        client.find_norm_hours("KIA", None)


def test_find_norm_hours_remote_raises_on_error_status(monkeypatch):
    client = AutoDataClient(base_url="http://1c.local/odata")

    monkeypatch.setattr(
        "app.services.autodata_client.requests.get",
        lambda *a, **kw: _FakeResponse(False, {}, status_code=500, text="server error"),
    )
    with pytest.raises(AutoDataError, match="500"):
        client.find_norm_hours("KIA", None)


def test_discover_entities_returns_object_names(monkeypatch):
    client = AutoDataClient(base_url="http://1c.local/odata")

    monkeypatch.setattr(
        "app.services.autodata_client.requests.get",
        lambda *a, **kw: _FakeResponse(True, {"value": [{"name": "Catalog_НормыВремени"}, {"name": "Catalog_Номенклатура"}]}),
    )
    assert client.discover_entities() == ["Catalog_НормыВремени", "Catalog_Номенклатура"]


def test_test_connection_remote_reports_discovered_entities(monkeypatch):
    client = AutoDataClient(base_url="http://1c.local/odata")

    monkeypatch.setattr(
        "app.services.autodata_client.requests.get",
        lambda *a, **kw: _FakeResponse(True, {"value": [{"name": "Catalog_НормыВремени"}]}),
    )
    message = client.test_connection()
    assert "1С OData отвечает" in message
    assert "Catalog_НормыВремени" in message
