def test_create_list_update_delete(client, admin_headers):
    create_resp = client.post(
        "/api/contragents",
        headers=admin_headers,
        json={"name": "СТО Восток", "hourly_rate": 1500, "notes": "основной подрядчик"},
    )
    assert create_resp.status_code == 201
    contragent_id = create_resp.get_json()["id"]

    list_resp = client.get("/api/contragents", headers=admin_headers)
    assert list_resp.status_code == 200
    assert any(c["id"] == contragent_id for c in list_resp.get_json())

    update_resp = client.patch(
        f"/api/contragents/{contragent_id}", headers=admin_headers, json={"hourly_rate": 1800}
    )
    assert update_resp.status_code == 200
    assert update_resp.get_json()["hourly_rate"] == 1800.0

    delete_resp = client.delete(f"/api/contragents/{contragent_id}", headers=admin_headers)
    assert delete_resp.status_code == 204
    assert client.get("/api/contragents", headers=admin_headers).get_json() == []


def test_create_requires_name_and_rate(client, admin_headers):
    assert client.post("/api/contragents", headers=admin_headers, json={"hourly_rate": 100}).status_code == 400
    assert client.post("/api/contragents", headers=admin_headers, json={"name": "X"}).status_code == 400


def test_create_rejects_negative_rate(client, admin_headers):
    resp = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "X", "hourly_rate": -10}
    )
    assert resp.status_code == 400


def test_create_rejects_duplicate_name(client, admin_headers):
    client.post("/api/contragents", headers=admin_headers, json={"name": "СТО Восток", "hourly_rate": 1000})
    resp = client.post("/api/contragents", headers=admin_headers, json={"name": "СТО Восток", "hourly_rate": 1200})
    assert resp.status_code == 409


def test_update_unknown_contragent_404(client, admin_headers):
    resp = client.patch("/api/contragents/99999", headers=admin_headers, json={"hourly_rate": 100})
    assert resp.status_code == 404
