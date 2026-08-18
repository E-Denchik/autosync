import io

import openpyxl


def _xlsx_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Артикул", "Наименование", "Цена"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_list_empty_by_default(client, operator_headers):
    resp = client.get("/api/contracts", headers=operator_headers)
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_and_list_and_delete(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)

    resp = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Гос. контракт №123", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202
    contract_id = resp.get_json()["id"]
    assert resp.get_json()["name"] == "Гос. контракт №123"
    assert resp.get_json()["parts_count"] == 0

    resp2 = client.get("/api/contracts", headers=admin_headers)
    assert len(resp2.get_json()) == 1

    resp3 = client.delete(f"/api/contracts/{contract_id}", headers=admin_headers)
    assert resp3.status_code == 204

    resp4 = client.get("/api/contracts", headers=admin_headers)
    assert resp4.get_json() == []


def test_delete_blocked_when_referenced_by_repair_order(client, admin_headers, app, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)

    resp = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    contract_id = resp.get_json()["id"]

    from app.extensions import db
    from app.models import RepairOrder, RepairOrderStatus

    with app.app_context():
        order = RepairOrder(
            contract_id=contract_id,
            original_filename="o.xlsx",
            storage_path="/tmp/o.xlsx",
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(order)
        db.session.commit()

    resp2 = client.delete(f"/api/contracts/{contract_id}", headers=admin_headers)
    assert resp2.status_code == 409


def test_parts_and_labor_norms_are_paginated(client, admin_headers, app):
    from app.extensions import db
    from app.models import Contract, ContractLaborNorm, ContractPart, DocumentProcessingStatus

    with app.app_context():
        contract = Contract(original_filename="c.xlsx", storage_path="/tmp/c.xlsx", status=DocumentProcessingStatus.PARSED)
        db.session.add(contract)
        db.session.flush()
        db.session.bulk_insert_mappings(
            ContractPart,
            [{"contract_id": contract.id, "article": f"A-{i}", "name": f"Деталь {i}", "price": i} for i in range(120)],
        )
        db.session.bulk_insert_mappings(
            ContractLaborNorm,
            [{"contract_id": contract.id, "operation_name": f"Работа {i}", "norm_hours": 1} for i in range(5)],
        )
        db.session.commit()
        contract_id = contract.id

    resp = client.get(f"/api/contracts/{contract_id}/parts?per_page=50", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()) == 50
    assert resp.headers["X-Total-Count"] == "120"

    resp2 = client.get(f"/api/contracts/{contract_id}/parts?q=Деталь 5", headers=admin_headers)
    assert all("5" in p["name"] for p in resp2.get_json())

    resp3 = client.get(f"/api/contracts/{contract_id}/labor-norms", headers=admin_headers)
    assert resp3.headers["X-Total-Count"] == "5"


def test_new_contract_is_active_by_default(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)
    resp = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.get_json()["active"] is True


def test_archive_and_unarchive_contract(client, admin_headers, operator_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)
    resp = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    contract_id = resp.get_json()["id"]

    archived = client.post(f"/api/contracts/{contract_id}/archive", headers=admin_headers)
    assert archived.status_code == 200
    assert archived.get_json()["active"] is False

    unarchived = client.post(f"/api/contracts/{contract_id}/unarchive", headers=admin_headers)
    assert unarchived.get_json()["active"] is True


def test_archived_contract_with_repair_orders_cannot_be_deleted_but_stays_archived(
    client, admin_headers, app, monkeypatch
):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)
    resp = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    contract_id = resp.get_json()["id"]

    from app.extensions import db
    from app.models import RepairOrder, RepairOrderStatus

    with app.app_context():
        order = RepairOrder(
            contract_id=contract_id,
            original_filename="o.xlsx",
            storage_path="/tmp/o.xlsx",
            status=RepairOrderStatus.UPLOADED,
        )
        db.session.add(order)
        db.session.commit()

    client.post(f"/api/contracts/{contract_id}/archive", headers=admin_headers)
    resp2 = client.delete(f"/api/contracts/{contract_id}", headers=admin_headers)
    assert resp2.status_code == 409

    resp3 = client.get(f"/api/contracts/{contract_id}", headers=admin_headers)
    assert resp3.get_json()["active"] is False


def test_hourly_rates_crud(client, admin_headers, operator_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)
    resp = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    contract_id = resp.get_json()["id"]

    created = client.post(
        f"/api/contracts/{contract_id}/hourly-rates",
        headers=admin_headers,
        json={"vehicle_make": "KIA", "hourly_rate": 1200},
    )
    assert created.status_code == 201
    rate_id = created.get_json()["id"]

    listed = client.get(f"/api/contracts/{contract_id}/hourly-rates", headers=operator_headers)
    assert listed.status_code == 200
    assert len(listed.get_json()) == 1
    assert listed.get_json()[0]["vehicle_make"] == "KIA"

    invalid = client.post(
        f"/api/contracts/{contract_id}/hourly-rates",
        headers=admin_headers,
        json={"vehicle_make": "", "hourly_rate": 1200},
    )
    assert invalid.status_code == 400

    deleted = client.delete(f"/api/contracts/{contract_id}/hourly-rates/{rate_id}", headers=admin_headers)
    assert deleted.status_code == 204

    listed2 = client.get(f"/api/contracts/{contract_id}/hourly-rates", headers=admin_headers)
    assert listed2.get_json() == []
