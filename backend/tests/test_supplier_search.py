from app.services.supplier_search import search_all_suppliers


def _cfg(**overrides):
    base = {
        "ROSSCO_KEY1": "",
        "ROSSCO_KEY2": "",
        "AUTOEURO_API_KEY": "",
        "MOSKVORECHYE_BASE_URL": "",
        "MOSKVORECHYE_API_KEY": "",
    }
    base.update(overrides)
    return base


def test_all_unconfigured_reports_hints_for_each_supplier():
    result = search_all_suppliers(_cfg(), "333114")
    assert result["results"] == []
    assert result["errors"] == []
    ids = {item["supplier"] for item in result["not_configured"]}
    assert ids == {"rossco", "autoeuro", "moskvorechye"}
    for item in result["not_configured"]:
        assert item["hint"]  # инструкция всегда непустая


def test_configured_supplier_error_is_reported_with_message(monkeypatch):
    from app.services.rossco_client import RosscoClient, RosscoError

    def fake_search_all(self, article, brand=None):
        raise RosscoError("клиент заблокирован")

    monkeypatch.setattr(RosscoClient, "search_all", fake_search_all)
    result = search_all_suppliers(_cfg(ROSSCO_KEY1="a", ROSSCO_KEY2="b"), "333114")

    assert result["results"] == []
    assert result["errors"] == [{"supplier": "rossco", "supplier_name": "Rossco", "message": "клиент заблокирован"}]
    assert {i["supplier"] for i in result["not_configured"]} == {"autoeuro", "moskvorechye"}


def test_configured_supplier_success_is_tagged_with_supplier_name(monkeypatch):
    from app.services.rossco_client import RosscoClient

    monkeypatch.setattr(
        RosscoClient, "search_all", lambda self, article, brand=None: [{"supplier": "rossco", "article": "333114"}]
    )
    result = search_all_suppliers(_cfg(ROSSCO_KEY1="a", ROSSCO_KEY2="b"), "333114")

    assert result["results"] == [{"supplier": "rossco", "article": "333114", "supplier_name": "Rossco"}]


def test_unexpected_exception_does_not_crash_search(monkeypatch):
    from app.services.rossco_client import RosscoClient

    def fake_search_all(self, article, brand=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(RosscoClient, "search_all", fake_search_all)
    result = search_all_suppliers(_cfg(ROSSCO_KEY1="a", ROSSCO_KEY2="b"), "333114")

    assert result["errors"][0]["supplier"] == "rossco"
    assert "boom" in result["errors"][0]["message"]
