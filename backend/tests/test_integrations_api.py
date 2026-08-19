from app.services.analytics_provider import AnalyticsProvider
from app.services.autoeuro_client import AutoEuroClient
from app.services.moskvorechye_client import MoskvorechyeClient
from app.services.ozon_client import OzonClient
from app.services.rossco_client import RosscoClient


def test_status_reports_not_configured_by_default(client, admin_headers):
    resp = client.get("/api/integrations/status", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    ids = {item["id"]: item["configured"] for item in body}
    assert ids == {
        "ozon_seller": False,
        "ozon_performance": False,
        "analytics": False,
        "alfaauto": False,
        "rossco": False,
        "autoeuro": False,
        "moskvorechye": False,
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


def test_test_connection_rossco_not_configured(client, admin_headers):
    resp = client.post("/api/integrations/test/rossco", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is False
    assert "ROSSCO_KEY1" in body["message"]


def test_test_connection_rossco_success(client, admin_headers, monkeypatch):
    monkeypatch.setattr(RosscoClient, "test_connection", lambda self: "Подключение работает, клиент: ООО Ромашка")
    client.post("/api/integrations/keys", headers=admin_headers, json={"ROSSCO_KEY1": "a", "ROSSCO_KEY2": "b"})
    resp = client.post("/api/integrations/test/rossco", headers=admin_headers)
    body = resp.get_json()
    assert body["ok"] is True
    assert "ООО Ромашка" in body["message"]


def test_test_connection_autoeuro_reports_inactive_account(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        AutoEuroClient, "get_balance", lambda self: {"balance": -100.0, "active": 0}
    )
    client.post("/api/integrations/keys", headers=admin_headers, json={"AUTOEURO_API_KEY": "k"})
    resp = client.post("/api/integrations/test/autoeuro", headers=admin_headers)
    body = resp.get_json()
    assert body["ok"] is True
    assert "НЕАКТИВЕН" in body["message"]


def test_test_connection_moskvorechye_not_configured(client, admin_headers):
    resp = client.post("/api/integrations/test/moskvorechye", headers=admin_headers)
    body = resp.get_json()
    assert body["ok"] is False
    assert "MOSKVORECHYE_BASE_URL" in body["message"]


def test_test_connection_moskvorechye_success(client, admin_headers, monkeypatch):
    monkeypatch.setattr(MoskvorechyeClient, "search_articles", lambda self, number, brand=None: [])
    client.post(
        "/api/integrations/keys",
        headers=admin_headers,
        json={"MOSKVORECHYE_BASE_URL": "https://example.abcp2b.ru", "MOSKVORECHYE_API_KEY": "login:pass"},
    )
    resp = client.post("/api/integrations/test/moskvorechye", headers=admin_headers)
    body = resp.get_json()
    assert body["ok"] is True


def test_save_keys_requires_at_least_one_value(client, admin_headers):
    resp = client.post("/api/integrations/keys", headers=admin_headers, json={})
    assert resp.status_code == 400


def test_save_keys_ignores_unknown_fields(client, admin_headers, app):
    original_data_dir = app.config["DATA_DIR"]
    resp = client.post(
        "/api/integrations/keys",
        headers=admin_headers,
        json={"DATA_DIR": "hijack", "OZON_CLIENT_ID": "cid-1"},
    )
    assert resp.status_code == 200
    assert app.config["DATA_DIR"] == original_data_dir
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
