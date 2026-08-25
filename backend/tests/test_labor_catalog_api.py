import os

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "testdata")


def test_import_file_creates_entries(client, admin_headers):
    path = os.path.join(TESTDATA_DIR, "Нормо-часы (справочник).xlsx")
    with open(path, "rb") as f:
        resp = client.post(
            "/api/labor-catalog/import",
            headers=admin_headers,
            data={"file": (f, "Нормо-часы (справочник).xlsx")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    assert resp.get_json() == {"created": 6, "updated": 0, "total": 6}

    listed = client.get("/api/labor-catalog", headers=admin_headers).get_json()
    assert len(listed) == 6
    assert any(e["source"] == "import" for e in listed)


def test_import_requires_file(client, admin_headers):
    resp = client.post("/api/labor-catalog/import", headers=admin_headers, data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_import_rejects_unparseable_file(client, admin_headers, tmp_path):
    bad_file = tmp_path / "bad.csv"
    bad_file.write_text("случайный текст без нужных колонок", encoding="utf-8")
    with open(bad_file, "rb") as f:
        resp = client.post(
            "/api/labor-catalog/import",
            headers=admin_headers,
            data={"file": (f, "bad.csv")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_list_empty_by_default(client, admin_headers):
    resp = client.get("/api/labor-catalog", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_list_update_delete(client, admin_headers):
    create_resp = client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "vehicle_model": "Rio", "operation_name": "Замена масла", "norm_hours": 0.5},
    )
    assert create_resp.status_code == 201
    body = create_resp.get_json()
    entry_id = body["id"]
    assert body["vehicle_make"] == "KIA"
    assert body["vehicle_model"] == "Rio"
    assert body["operation_name"] == "Замена масла"
    assert body["norm_hours"] == 0.5
    assert body["source"] == "manual"

    listed = client.get("/api/labor-catalog", headers=admin_headers).get_json()
    assert len(listed) == 1
    assert listed[0]["id"] == entry_id

    updated = client.patch(
        f"/api/labor-catalog/{entry_id}", headers=admin_headers, json={"norm_hours": 0.8}
    )
    assert updated.status_code == 200
    assert updated.get_json()["norm_hours"] == 0.8

    deleted = client.delete(f"/api/labor-catalog/{entry_id}", headers=admin_headers)
    assert deleted.status_code == 204
    assert client.get("/api/labor-catalog", headers=admin_headers).get_json() == []


def test_create_allows_empty_vehicle_model(client, admin_headers):
    """vehicle_model необязателен — запись общая для всех моделей марки
    (см. AutoDataClient._find_local: фильтр по model опционален)."""
    resp = client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "operation_name": "Замена масла", "norm_hours": 0.5},
    )
    assert resp.status_code == 201
    assert resp.get_json()["vehicle_model"] is None


def test_create_requires_vehicle_make_and_operation_name(client, admin_headers):
    missing_make = client.post(
        "/api/labor-catalog", headers=admin_headers, json={"operation_name": "x", "norm_hours": 1}
    )
    assert missing_make.status_code == 400

    missing_operation = client.post(
        "/api/labor-catalog", headers=admin_headers, json={"vehicle_make": "KIA", "norm_hours": 1}
    )
    assert missing_operation.status_code == 400


def test_create_rejects_non_numeric_norm_hours(client, admin_headers):
    resp = client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "operation_name": "x", "norm_hours": "not-a-number"},
    )
    assert resp.status_code == 400


def test_create_rejects_zero_or_negative_norm_hours(client, admin_headers):
    for value in (0, -1):
        resp = client.post(
            "/api/labor-catalog",
            headers=admin_headers,
            json={"vehicle_make": "KIA", "operation_name": "x", "norm_hours": value},
        )
        assert resp.status_code == 400


def test_update_rejects_non_numeric_norm_hours(client, admin_headers):
    entry_id = client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "operation_name": "x", "norm_hours": 1},
    ).get_json()["id"]

    resp = client.patch(
        f"/api/labor-catalog/{entry_id}", headers=admin_headers, json={"norm_hours": "not-a-number"}
    )
    assert resp.status_code == 400


def test_update_vehicle_make_and_operation_name(client, admin_headers):
    entry_id = client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "operation_name": "Замена масла", "norm_hours": 1},
    ).get_json()["id"]

    resp = client.patch(
        f"/api/labor-catalog/{entry_id}",
        headers=admin_headers,
        json={"vehicle_make": "HYUNDAI", "vehicle_model": "Solaris", "operation_name": "Замена фильтра"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["vehicle_make"] == "HYUNDAI"
    assert body["vehicle_model"] == "Solaris"
    assert body["operation_name"] == "Замена фильтра"


def test_update_unknown_entry_404(client, admin_headers):
    resp = client.patch("/api/labor-catalog/999999", headers=admin_headers, json={"norm_hours": 1})
    assert resp.status_code == 404


def test_delete_unknown_entry_404(client, admin_headers):
    resp = client.delete("/api/labor-catalog/999999", headers=admin_headers)
    assert resp.status_code == 404


def test_list_orders_by_make_model_operation(client, admin_headers):
    client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "operation_name": "Замена масла", "norm_hours": 1},
    )
    client.post(
        "/api/labor-catalog",
        headers=admin_headers,
        json={"vehicle_make": "HYUNDAI", "operation_name": "Замена фильтра", "norm_hours": 1},
    )

    listed = client.get("/api/labor-catalog", headers=admin_headers).get_json()
    assert [e["vehicle_make"] for e in listed] == ["HYUNDAI", "KIA"]
