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


def test_connection_refused_raises_analytics_provider_error_not_raw_exception(monkeypatch):
    import requests

    provider = AnalyticsProvider("https://example.com", "key")

    def fake_get(url, params=None, headers=None, timeout=None):
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr("app.services.analytics_provider.requests.get", fake_get)
    with pytest.raises(AnalyticsProviderError, match="недоступен"):
        provider.test_connection()


def test_get_top_competitor_listings_normalizes_results(monkeypatch):
    provider = AnalyticsProvider("https://example.com", "key")
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(
            True,
            {
                "results": [
                    {
                        "name": "Тормозной диск AAA",
                        "price": 1200,
                        "sales_rank": 1,
                        "units_sold_30d": 340,
                        "rating": 4.8,
                        "reviews_count": 120,
                        "irrelevant_field": "должно быть отброшено",
                    },
                    {"name": "Тормозной диск BBB", "price": 1350},
                ]
            },
        )

    monkeypatch.setattr("app.services.analytics_provider.requests.get", fake_get)
    listings = provider.get_top_competitor_listings("тормозной диск", "Тормозная система", limit=5)

    assert captured["url"] == "https://example.com/v1/competitors/top-listings"
    assert captured["params"] == {"query": "тормозной диск", "category": "Тормозная система", "limit": 5}
    assert listings == [
        {
            "name": "Тормозной диск AAA",
            "price": 1200,
            "sales_rank": 1,
            "units_sold_30d": 340,
            "rating": 4.8,
            "reviews_count": 120,
        },
        {
            "name": "Тормозной диск BBB",
            "price": 1350,
            "sales_rank": None,
            "units_sold_30d": None,
            "rating": None,
            "reviews_count": None,
        },
    ]


def test_get_top_competitor_listings_empty_results(monkeypatch):
    provider = AnalyticsProvider("https://example.com", "key")

    monkeypatch.setattr(
        "app.services.analytics_provider.requests.get",
        lambda url, params=None, headers=None, timeout=None: _FakeResponse(True, {}),
    )
    assert provider.get_top_competitor_listings("что угодно") == []


def test_get_top_competitor_listings_failure_raises(monkeypatch):
    provider = AnalyticsProvider("https://example.com", "key")

    monkeypatch.setattr(
        "app.services.analytics_provider.requests.get",
        lambda url, params=None, headers=None, timeout=None: _FakeResponse(
            False, {}, status_code=500, text="boom"
        ),
    )
    with pytest.raises(AnalyticsProviderError, match="500"):
        provider.get_top_competitor_listings("что угодно")
