def test_search_requires_article(client, admin_headers):
    resp = client.get("/api/parts-suppliers/search", headers=admin_headers)
    assert resp.status_code == 400


def test_search_reports_not_configured_by_default(client, admin_headers):
    resp = client.get("/api/parts-suppliers/search?article=333114", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["results"] == []
    assert body["errors"] == []
    assert len(body["not_configured"]) == 3


def test_search_passes_brand_through(client, admin_headers, monkeypatch):
    from app.services.rossco_client import RosscoClient

    captured = {}

    def fake_search_all(self, article, brand=None):
        captured["article"] = article
        captured["brand"] = brand
        return []

    monkeypatch.setattr(RosscoClient, "search_all", fake_search_all)
    client.post("/api/integrations/keys", headers=admin_headers, json={"ROSSCO_KEY1": "a", "ROSSCO_KEY2": "b"})
    client.get("/api/parts-suppliers/search?article=333114&brand=KYB", headers=admin_headers)

    assert captured == {"article": "333114", "brand": "KYB"}
