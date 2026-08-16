import io

import pandas as pd
import pytest


def _xlsx_bytes(rows):
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer


def test_preview_requires_auth(client):
    resp = client.post("/api/file-preview", data={}, content_type="multipart/form-data")
    assert resp.status_code == 401


def test_preview_requires_file(client, operator_headers):
    resp = client.post("/api/file-preview", headers=operator_headers, data={}, content_type="multipart/form-data")
    assert resp.status_code == 400


def test_preview_rejects_unsupported_extension(client, operator_headers):
    resp = client.post(
        "/api/file-preview",
        headers=operator_headers,
        data={"file": (io.BytesIO(b"binary"), "image.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_preview_returns_rows_for_xlsx(client, operator_headers):
    rows = [{"Артикул": "A-1", "Наименование": "Фильтр"}, {"Артикул": "A-2", "Наименование": "Диск"}]
    resp = client.post(
        "/api/file-preview",
        headers=operator_headers,
        data={"file": (_xlsx_bytes(rows), "price.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["rows"][0] == ["Артикул", "Наименование"]
    assert body["rows"][1] == ["A-1", "Фильтр"]
    assert body["rows"][2] == ["A-2", "Диск"]
    assert body["truncated"] is False


def test_preview_truncates_large_files(client, operator_headers):
    rows = [{"n": i} for i in range(250)]
    resp = client.post(
        "/api/file-preview",
        headers=operator_headers,
        data={"file": (_xlsx_bytes(rows), "big.xlsx")},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert body["truncated"] is True
    assert len(body["rows"]) == 201


@pytest.fixture
def repair_order_with_files(app):
    import tempfile

    from app.extensions import db
    from app.models import Contract, DocumentProcessingStatus, RepairOrder, RepairOrderStatus

    with app.app_context():
        contract_path = tempfile.mktemp(suffix=".xlsx")
        _xlsx_bytes([{"Артикул": "X-1", "Наименование": "Тест"}]).seek(0)
        with open(contract_path, "wb") as f:
            f.write(_xlsx_bytes([{"Артикул": "X-1", "Наименование": "Тест"}]).read())

        contract = Contract(
            original_filename="contract.xlsx",
            storage_path=contract_path,
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()

        order_path = tempfile.mktemp(suffix=".xlsx")
        with open(order_path, "wb") as f:
            f.write(_xlsx_bytes([{"Артикул": "Y-1", "Наименование": "Наряд"}]).read())

        order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path=order_path,
            status=RepairOrderStatus.NEEDS_REVIEW,
        )
        db.session.add(order)
        db.session.commit()
        return order.id


def test_download_source_file_order(client, admin_headers, repair_order_with_files):
    resp = client.get(
        f"/api/repair-orders/upload/{repair_order_with_files}/file?source=order", headers=admin_headers
    )
    assert resp.status_code == 200


def test_download_source_file_contract(client, admin_headers, repair_order_with_files):
    resp = client.get(
        f"/api/repair-orders/upload/{repair_order_with_files}/file?source=contract", headers=admin_headers
    )
    assert resp.status_code == 200


def test_download_source_file_invalid_source(client, admin_headers, repair_order_with_files):
    resp = client.get(
        f"/api/repair-orders/upload/{repair_order_with_files}/file?source=bogus", headers=admin_headers
    )
    assert resp.status_code == 400
