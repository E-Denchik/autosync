import io

import openpyxl


def _xlsx_bytes():
    wb = openpyxl.Workbook()
    wb.active.append(["{{order_number}}"])
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
