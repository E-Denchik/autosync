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
    assert ids == {"ozon_seller": False, "ozon_performance": False, "analytics": False}


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
