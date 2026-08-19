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


def test_hourly_rates_crud(client, admin_headers):
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "СТО Восток", "hourly_rate": 1000}
    ).get_json()["id"]

    created = client.post(
        f"/api/contragents/{contragent_id}/hourly-rates",
        headers=admin_headers,
        json={"vehicle_make": "VOLKSWAGEN", "hourly_rate": 800},
    )
    assert created.status_code == 201
    rate_id = created.get_json()["id"]

    listed = client.get(f"/api/contragents/{contragent_id}/hourly-rates", headers=admin_headers)
    assert listed.status_code == 200
    assert len(listed.get_json()) == 1
    assert listed.get_json()[0]["vehicle_make"] == "VOLKSWAGEN"
    assert listed.get_json()[0]["hourly_rate"] == 800.0

    invalid = client.post(
        f"/api/contragents/{contragent_id}/hourly-rates",
        headers=admin_headers,
        json={"vehicle_make": "", "hourly_rate": 800},
    )
    assert invalid.status_code == 400

    deleted = client.delete(f"/api/contragents/{contragent_id}/hourly-rates/{rate_id}", headers=admin_headers)
    assert deleted.status_code == 204

    listed2 = client.get(f"/api/contragents/{contragent_id}/hourly-rates", headers=admin_headers)
    assert listed2.get_json() == []


def test_deleting_contragent_cascades_hourly_rates(app, admin_headers, client):
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "СТО Запад", "hourly_rate": 1000}
    ).get_json()["id"]
    client.post(
        f"/api/contragents/{contragent_id}/hourly-rates",
        headers=admin_headers,
        json={"vehicle_make": "TOYOTA", "hourly_rate": 1200},
    )

    client.delete(f"/api/contragents/{contragent_id}", headers=admin_headers)

    with app.app_context():
        from app.models import ContragentHourlyRate

        assert ContragentHourlyRate.query.filter_by(contragent_id=contragent_id).count() == 0
