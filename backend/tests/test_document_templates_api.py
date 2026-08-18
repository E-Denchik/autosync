import io

import openpyxl
import pytest


def _xlsx_bytes():
    wb = openpyxl.Workbook()
    wb.active.append(["{{order_number}}"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _xlsx_bytes_with_malformed_token():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["{{order_number}}"])
    ws.append(["{{order date}}"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_list_templates_empty_by_default(client, operator_headers):
    resp = client.get("/api/document-templates", headers=operator_headers)
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_upload_rejects_unsupported_extension(client, admin_headers):
    resp = client.post(
        "/api/document-templates",
        headers=admin_headers,
        data={"name": "Акт", "file": (io.BytesIO(b"not excel"), "act.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_and_list_and_delete(client, admin_headers):
    resp = client.post(
        "/api/document-templates",
        headers=admin_headers,
        data={"name": "Акт выполненных работ", "file": (_xlsx_bytes(), "act.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    template_id = resp.get_json()["id"]
    assert resp.get_json()["name"] == "Акт выполненных работ"

    resp2 = client.get("/api/document-templates", headers=admin_headers)
    assert len(resp2.get_json()) == 1

    resp_file = client.get(f"/api/document-templates/{template_id}/file", headers=admin_headers)
    assert resp_file.status_code == 200

    resp3 = client.delete(f"/api/document-templates/{template_id}", headers=admin_headers)
    assert resp3.status_code == 204

    resp4 = client.get("/api/document-templates", headers=admin_headers)
    assert resp4.get_json() == []


def test_download_starter_template(client, operator_headers):
    resp = client.get("/api/document-templates/starter", headers=operator_headers)
    assert resp.status_code == 200
    assert resp.mimetype in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    )


@pytest.fixture
def repair_order(app):
    from app.extensions import db
    from app.models import Contract, Contragent, DocumentProcessingStatus, RepairOrder, RepairOrderStatus

    with app.app_context():
        contract = Contract(
            original_filename="contract.xlsx",
            storage_path="/tmp/contract.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        contragent = Contragent(name="СТО Восток", hourly_rate=1500)
        db.session.add_all([contract, contragent])
        db.session.flush()

        order = RepairOrder(
            contract_id=contract.id,
            contragent_id=contragent.id,
            original_filename="order.xlsx",
            storage_path="/tmp/order.xlsx",
            status=RepairOrderStatus.NEEDS_REVIEW,
            vehicle_make="ВАЗ",
            vehicle_model="Granta",
        )
        db.session.add(order)
        db.session.commit()
        return order.id


def test_preview_rendered_requires_a_repair_order(client, admin_headers):
    resp = client.post(
        "/api/document-templates/preview-rendered",
        headers=admin_headers,
        data={"file": (_xlsx_bytes(), "act.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_preview_rendered_substitutes_real_data_for_uploaded_file(client, admin_headers, repair_order):
    resp = client.post(
        "/api/document-templates/preview-rendered",
        headers=admin_headers,
        data={"file": (_xlsx_bytes(), "act.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["repair_order_id"] == repair_order
    assert body["unresolved_tokens"] == []
    flat = [cell for row in body["rows"] for cell in row]
    assert str(repair_order) in flat
    assert not any("{{" in cell for cell in flat)


def test_preview_rendered_reports_unresolved_tokens(client, admin_headers, repair_order):
    resp = client.post(
        "/api/document-templates/preview-rendered",
        headers=admin_headers,
        data={"file": (_xlsx_bytes_with_malformed_token(), "act.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["unresolved_tokens"] == ["{{order date}}"]


def test_preview_rendered_substitutes_real_data_for_saved_template(client, admin_headers, repair_order):
    upload_resp = client.post(
        "/api/document-templates",
        headers=admin_headers,
        data={"name": "Акт", "file": (_xlsx_bytes(), "act.xlsx")},
        content_type="multipart/form-data",
    )
    template_id = upload_resp.get_json()["id"]

    resp = client.post(
        "/api/document-templates/preview-rendered",
        headers=admin_headers,
        data={"template_id": template_id},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    flat = [cell for row in body["rows"] for cell in row]
    assert str(repair_order) in flat
    assert not any("{{" in cell for cell in flat)
