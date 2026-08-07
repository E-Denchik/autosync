from app.services.analytics_provider import AnalyticsProvider
from app.services.ozon_client import OzonClient


def test_status_requires_admin(client, operator_headers):
    resp = client.get("/api/integrations/status", headers=operator_headers)
    assert resp.status_code == 403


def test_status_requires_auth(client):
    resp = client.get("/api/integrations/status")
    assert resp.status_code == 401


def test_status_reports_not_configured_by_default(client, admin_headers):
    resp = client.get("/api/integrations/status", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {item["id"]: item["configured"] for item in body}
    assert ids == {
        "ozon_seller": False,
        "ozon_performance": False,
        "analytics": False,
        "nomenclature": False,
    }
    assert all(item["api_base_override"] is None for item in body)


def test_status_reports_api_base_override(client, admin_headers, monkeypatch):
    monkeypatch.setenv("OZON_SELLER_API_BASE", "http://127.0.0.1:5900")
    resp = client.get("/api/integrations/status", headers=admin_headers)
    body = {item["id"]: item for item in resp.get_json()}
    assert body["ozon_seller"]["api_base_override"] == "http://127.0.0.1:5900"
    assert body["ozon_performance"]["api_base_override"] is None


def test_test_connection_unknown_integration(client, admin_headers):
    resp = client.post("/api/integrations/test/does_not_exist", headers=admin_headers)
    assert resp.status_code == 404


def test_test_connection_ozon_seller_not_configured(client, admin_headers):
    resp = client.post("/api/integrations/test/ozon_seller", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "OZON_CLIENT_ID" in body["message"]


def test_test_connection_ozon_seller_success(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        OzonClient, "test_seller_connection", lambda self: "Подключение работает, товаров в кабинете: 10"
    )
    resp = client.post("/api/integrations/test/ozon_seller", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert "10" in body["message"]


def test_test_connection_analytics_not_configured(client, admin_headers):
    resp = client.post("/api/integrations/test/analytics", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "ANALYTICS_PROVIDER_BASE_URL" in body["message"]


def test_test_connection_unexpected_error_is_not_500(client, admin_headers, monkeypatch):
    def _raise(self):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(OzonClient, "test_seller_connection", _raise)
    resp = client.post("/api/integrations/test/ozon_seller", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False


def test_save_keys_requires_admin(client, operator_headers):
    resp = client.post(
        "/api/integrations/keys", headers=operator_headers, json={"OZON_CLIENT_ID": "x"}
    )
    assert resp.status_code == 403


def test_save_keys_requires_at_least_one_value(client, admin_headers):
    resp = client.post("/api/integrations/keys", headers=admin_headers, json={})
    assert resp.status_code == 400


def test_save_keys_ignores_unknown_fields(client, admin_headers, app):
    resp = client.post(
        "/api/integrations/keys",
        headers=admin_headers,
        json={"SECRET_KEY": "hijack", "OZON_CLIENT_ID": "cid-1"},
    )
    assert resp.status_code == 200
    assert app.config["SECRET_KEY"] != "hijack"
    assert app.config["OZON_CLIENT_ID"] == "cid-1"


def test_save_keys_persists_to_db_and_applies_immediately(client, admin_headers, app):
    resp = client.post(
        "/api/integrations/keys",
        headers=admin_headers,
        json={"OZON_CLIENT_ID": "cid-123", "OZON_API_KEY": "key-456"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["updated"] == ["OZON_API_KEY", "OZON_CLIENT_ID"]

    # применилось сразу, без перезапуска процесса
    assert app.config["OZON_CLIENT_ID"] == "cid-123"
    assert app.config["OZON_API_KEY"] == "key-456"

    # и сохранилось в БД
    from app.services import settings_store

    with app.app_context():
        values = settings_store.load_all()
    assert values["OZON_CLIENT_ID"] == "cid-123"
    assert values["OZON_API_KEY"] == "key-456"


def test_save_keys_status_reflects_saved_keys(client, admin_headers):
    client.post(
        "/api/integrations/keys",
        headers=admin_headers,
        json={"OZON_CLIENT_ID": "cid", "OZON_API_KEY": "key"},
    )
    resp = client.get("/api/integrations/status", headers=admin_headers)
    ids = {item["id"]: item["configured"] for item in resp.get_json()}
    assert ids["ozon_seller"] is True
