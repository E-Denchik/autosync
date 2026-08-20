import io
import os

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


def test_upload_reuses_already_parsed_contract(client, admin_headers, app, monkeypatch):
    monkeypatch.setattr("app.api.repair_orders.upload.enqueue_process_upload", lambda *a, **kw: None)

    with app.app_context():
        contract = Contract(
            original_filename="existing.xlsx",
            storage_path="/tmp/existing.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.commit()
        contract_id = contract.id

    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data={"contract_id": str(contract_id), "repair_order": (io.BytesIO(b"x"), "order.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["contract_id"] == contract_id

    with app.app_context():
        order = db.session.get(RepairOrder, body["repair_order_id"])
        assert order.contract_id == contract_id


def test_uploading_a_new_contract_file_reuses_an_existing_identical_one(client, admin_headers, app, monkeypatch):
    """Регрессия: заказчик выбирает «Новый файл» вместо «Уже загруженный
    контракт» по привычке и каждый раз плодит отдельный договор — теперь
    при совпадении содержимого файла с уже разобранным договором он
    переиспользуется автоматически, новый не создаётся."""
    monkeypatch.setattr("app.api.repair_orders.upload.enqueue_process_upload", lambda *a, **kw: None)

    # Готовим существующий договор через реальный compute_files_hash, чтобы
    # не дублировать логику подсчёта хэша в тесте.
    from app.services.upload_helpers import compute_files_hash

    with app.app_context():
        tmp_path = os.path.join(app.config["UPLOAD_DIR"], "existing-contract.xlsx")
        os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
        with open(tmp_path, "wb") as f:
            f.write(b"same contract bytes")
        content_hash = compute_files_hash([tmp_path])

        contract = Contract(
            original_filename="прайс.xlsx",
            storage_path=tmp_path,
            content_hash=content_hash,
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.commit()
        contract_id = contract.id

    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data={
            "contract": (io.BytesIO(b"same contract bytes"), "прайс.xlsx"),
            "repair_order": (io.BytesIO(b"order bytes"), "order.xlsx"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["contract_id"] == contract_id
    assert body["reused_existing_contract"] is True

    with app.app_context():
        assert Contract.query.count() == 1


def test_uploading_a_new_contract_file_with_different_content_creates_a_new_contract(
    client, admin_headers, app, monkeypatch
):
    monkeypatch.setattr("app.api.repair_orders.upload.enqueue_process_upload", lambda *a, **kw: None)

    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data=_files(),
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202
    assert resp.get_json()["reused_existing_contract"] is False


def test_upload_rejects_reusing_a_contract_still_being_parsed(client, admin_headers, app):
    with app.app_context():
        contract = Contract(
            original_filename="pending.xlsx",
            storage_path="/tmp/pending.xlsx",
            status=DocumentProcessingStatus.PARSING,
        )
        db.session.add(contract)
        db.session.commit()
        contract_id = contract.id

    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data={"contract_id": str(contract_id), "repair_order": (io.BytesIO(b"x"), "order.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 409


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


def test_status_reports_contragent_and_vehicle_so_ui_can_confirm_they_were_saved(
    client, admin_headers, app, monkeypatch
):
    """Регрессия: заказчик засомневался, что выбранный на странице загрузки
    контрагент реально сохраняется — раньше страница проверки вообще не
    показывала эту информацию, поэтому не было способа убедиться."""
    monkeypatch.setattr("app.api.repair_orders.upload.enqueue_process_upload", lambda *a, **kw: None)

    from app.extensions import db
    from app.models import Contragent

    with app.app_context():
        contragent = Contragent(name="СТО Восток", hourly_rate=1500)
        db.session.add(contragent)
        db.session.commit()
        contragent_id = contragent.id

    resp = client.post(
        "/api/repair-orders/upload",
        headers=admin_headers,
        data={
            **_files(),
            "contragent_id": str(contragent_id),
            "vehicle_make": "KIA",
            "vehicle_model": "Rio",
        },
        content_type="multipart/form-data",
    )
    repair_order_id = resp.get_json()["repair_order_id"]

    status_resp = client.get(
        f"/api/repair-orders/upload/{repair_order_id}/status", headers=admin_headers
    )
    body = status_resp.get_json()
    assert body["contragent_name"] == "СТО Восток"
    assert body["vehicle_make"] == "KIA"
    assert body["vehicle_model"] == "Rio"
