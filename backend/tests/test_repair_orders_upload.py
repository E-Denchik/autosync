import io

from app.extensions import db
from app.models import Contract, DocumentProcessingStatus, RepairOrder, RepairOrderStatus


def _files():
    return {
        "contract": (io.BytesIO(b"fake xlsx bytes"), "contract.xlsx"),
        "repair_order": (io.BytesIO(b"fake xlsx bytes"), "order.xlsx"),
    }


def test_upload_requires_both_files(client, admin_headers):
    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data={"contract": (io.BytesIO(b"x"), "contract.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_rejects_unsupported_extension(client, admin_headers):
    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data={
            "contract": (io.BytesIO(b"x"), "contract.exe"),
            "repair_order": (io.BytesIO(b"x"), "order.xlsx"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_creates_records_and_enqueues_processing(client, admin_headers, app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.api.repair_orders.upload.enqueue_process_upload",
        lambda contract_id, repair_order_id: calls.append((contract_id, repair_order_id)),
    )

    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data=_files(),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert calls == [(body["contract_id"], body["repair_order_id"])]

    with app.app_context():
        contract = db.session.get(Contract, body["contract_id"])
        order = db.session.get(RepairOrder, body["repair_order_id"])
        assert contract.status == DocumentProcessingStatus.UPLOADED
        assert order.status == RepairOrderStatus.UPLOADED
        assert order.contract_id == contract.id


def test_upload_requires_auth(client):
    resp = client.post(
        "/api/repair-orders/upload", data=_files(), content_type="multipart/form-data"
    )
    assert resp.status_code == 401


def test_list_and_status_endpoints(client, admin_headers, app, monkeypatch):
    monkeypatch.setattr(
        "app.api.repair_orders.upload.enqueue_process_upload", lambda *a, **kw: None
    )
    upload_resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data=_files(),
        content_type="multipart/form-data",
    )
    repair_order_id = upload_resp.get_json()["repair_order_id"]

    list_resp = client.get("/api/repair-orders/upload", headers=admin_headers)
    assert list_resp.status_code == 200
    ids = [o["id"] for o in list_resp.get_json()]
    assert repair_order_id in ids

    status_resp = client.get(
        f"/api/repair-orders/upload/{repair_order_id}/status", headers=admin_headers
    )
    assert status_resp.status_code == 200
    assert status_resp.get_json()["status"] == "uploaded"
