import pytest

from app.services.rossco_client import RosscoClient, RosscoError


class _FakeService:
    def __init__(self, response):
        self._response = response

    def GetSearch(self, **kwargs):
        self.last_call = kwargs
        return self._response

    def GetCheckoutDetails(self, **kwargs):
        self.last_call = kwargs
        return self._response


class _FakeZeepClient:
    def __init__(self, response):
        self.service = _FakeService(response)


def test_search_without_keys_raises():
    client = RosscoClient(key1="", key2="")
    with pytest.raises(RosscoError, match="ROSSCO_KEY1"):
        client.search("333114")


def test_search_raises_on_unsuccessful_response(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    monkeypatch.setattr(client, "_client", lambda method: _FakeZeepClient({"success": False, "message": "не найдено"}))

    with pytest.raises(RosscoError, match="не найдено"):
        client.search("does-not-exist")


def test_search_defaults_to_pickup_delivery(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    fake = _FakeZeepClient({"success": True, "PartsList": {}})
    monkeypatch.setattr(client, "_client", lambda method: fake)

    client.search("333114")

    assert fake.service.last_call["delivery_id"] == "000000001"
    assert "address_id" not in fake.service.last_call


def test_find_cross_references_extracts_crosses_only(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    response = {
        "success": True,
        "PartsList": {
            "Part": {
                "partnumber": "333114",
                "brand": "KYB",
                "crosses": {
                    "Part": [
                        {
                            "partnumber": "290 074",
                            "brand": "Sachs",
                            "name": "Амортизатор",
                            "stocks": {"stock": [{"price": "10920.33"}]},
                        }
                    ]
                },
            }
        },
    }
    monkeypatch.setattr(client, "_client", lambda method: _FakeZeepClient(response))

    refs = client.find_cross_references("333114")

    assert refs == [{"article": "290 074", "brand": "Sachs", "name": "Амортизатор", "price": 10920.33}]


def test_find_cross_references_includes_brand_in_search_text(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    fake = _FakeZeepClient({"success": True, "PartsList": {}})
    monkeypatch.setattr(client, "_client", lambda method: fake)

    client.find_cross_references("PN32661", brand="AUTOWELT")

    assert fake.service.last_call["text"] == "AUTOWELT PN32661"


def test_find_cross_references_returns_empty_on_error(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    monkeypatch.setattr(client, "_client", lambda method: _FakeZeepClient({"success": False, "message": "boom"}))

    assert client.find_cross_references("333114") == []


def test_test_connection_reports_company_name(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    response = {"success": True, "CompanyList": {"company": {"name": "ИП Иванов"}}}
    monkeypatch.setattr(client, "_client", lambda method: _FakeZeepClient(response))

    message = client.test_connection()
    assert "ИП Иванов" in message


def test_search_all_includes_exact_match_and_crosses(monkeypatch):
    client = RosscoClient(key1="k1", key2="k2")
    response = {
        "success": True,
        "PartsList": {
            "Part": {
                "partnumber": "333114",
                "brand": "KYB",
                "name": "Стойка амортизационная",
                "stocks": {"stock": [{"price": "5399", "count": 2}, {"price": "6829", "count": 1}]},
                "crosses": {
                    "Part": [
                        {
                            "partnumber": "290 074",
                            "brand": "Sachs",
                            "name": "Амортизатор",
                            "stocks": {"stock": [{"price": "10920.33", "count": 3}]},
                        }
                    ]
                },
            }
        },
    }
    monkeypatch.setattr(client, "_client", lambda method: _FakeZeepClient(response))

    items = client.search_all("333114")

    assert items == [
        {"supplier": "rossco", "article": "333114", "brand": "KYB", "name": "Стойка амортизационная", "price": 5399.0, "amount": 3},
        {"supplier": "rossco", "article": "290 074", "brand": "Sachs", "name": "Амортизатор", "price": 10920.33, "amount": 3},
    ]


def test_search_all_raises_on_error_unlike_find_cross_references(monkeypatch):
    """search_all — для UI поиска по поставщикам — не должен молча
    проглатывать ошибку, в отличие от find_cross_references (внутренний
    фоллбэк для matcher.py, где отсутствие результата — нормальный исход)."""
    client = RosscoClient(key1="k1", key2="k2")
    monkeypatch.setattr(client, "_client", lambda method: _FakeZeepClient({"success": False, "message": "boom"}))

    with pytest.raises(RosscoError, match="boom"):
        client.search_all("333114")
