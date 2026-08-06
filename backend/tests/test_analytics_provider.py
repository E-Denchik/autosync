import pytest

from app.services.analytics_provider import AnalyticsProvider, AnalyticsProviderError


class _FakeResponse:
    def __init__(self, ok, json_data, status_code=200, text=""):
        self.ok = ok
        self._json = json_data
        self.status_code = status_code
        self.text = text or str(json_data)

    def json(self):
        return self._json


def test_init_without_base_url_raises():
    with pytest.raises(AnalyticsProviderError, match="ANALYTICS_PROVIDER_BASE_URL"):
        AnalyticsProvider("", "key")


def test_connection_success(monkeypatch):
    provider = AnalyticsProvider("https://example.com", "key")

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == "https://example.com/v1/competitors"
        assert headers["Authorization"] == "Bearer key"
        return _FakeResponse(True, {"min_price": 100, "avg_price": 150})

    monkeypatch.setattr("app.services.analytics_provider.requests.get", fake_get)
    message = provider.test_connection()
    assert "100" in message and "150" in message


def test_connection_failure_raises(monkeypatch):
    provider = AnalyticsProvider("https://example.com", "key")

    def fake_get(url, params=None, headers=None, timeout=None):
        return _FakeResponse(False, {}, status_code=404, text="Not Found")

    monkeypatch.setattr("app.services.analytics_provider.requests.get", fake_get)
    with pytest.raises(AnalyticsProviderError, match="404"):
        provider.test_connection()
