import io

import pandas as pd

from app.extensions import db
from app.models import NomenclatureEntry


def _xlsx_bytes(rows):
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer


def test_create_list_update_delete_entry(client, admin_headers):
    create_resp = client.post(
        "/api/nomenclature",
        headers=admin_headers,
        json={"name": "Рычаг развальный С/У", "code": "PN-1", "stock_qty": 3},
    )
    assert create_resp.status_code == 201
    entry_id = create_resp.get_json()["id"]

    list_resp = client.get("/api/nomenclature", headers=admin_headers)
    assert list_resp.status_code == 200
    assert any(e["id"] == entry_id for e in list_resp.get_json())

    search_resp = client.get("/api/nomenclature?q=развальный", headers=admin_headers)
    assert any(e["id"] == entry_id for e in search_resp.get_json())

    update_resp = client.patch(
        f"/api/nomenclature/{entry_id}", headers=admin_headers, json={"stock_qty": 7}
    )
    assert update_resp.status_code == 200
    assert update_resp.get_json()["stock_qty"] == 7.0

    delete_resp = client.delete(f"/api/nomenclature/{entry_id}", headers=admin_headers)
    assert delete_resp.status_code == 204


def test_create_requires_name(client, admin_headers):
    resp = client.post("/api/nomenclature", headers=admin_headers, json={"code": "PN-1"})
    assert resp.status_code == 400


def test_upload_rejects_unsupported_extension(client, admin_headers):
    resp = client.post(
        "/api/nomenclature/upload",
        headers=admin_headers,
        data={"file": (io.BytesIO(b"x"), "nomenclature.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_upload_imports_rows(client, admin_headers, app):
    rows = [
        {"Код": "PN-2", "Номенклатура": "Фильтр воздушный", "Остаток": 5, "Склад": "Основной"},
    ]
    resp = client.post(
        "/api/nomenclature/upload",
        headers=admin_headers,
        data={"file": (_xlsx_bytes(rows), "nomenclature.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    assert resp.get_json() == {"rows_parsed": 1, "created": 1, "updated": 0, "errors": []}

    with app.app_context():
        entry = NomenclatureEntry.query.filter_by(code="PN-2").first()
        assert entry is not None
        assert float(entry.stock_qty) == 5.0


def test_template_download_roundtrips_through_upload(client, admin_headers, app):
    import io

    tpl_resp = client.get("/api/nomenclature/template", headers=admin_headers)
    assert tpl_resp.status_code == 200

    upload_resp = client.post(
        "/api/nomenclature/upload",
        headers=admin_headers,
        data={"file": (io.BytesIO(tpl_resp.data), "template.xlsx")},
        content_type="multipart/form-data",
    )
    assert upload_resp.status_code == 201
    body = upload_resp.get_json()
    assert body["created"] == 1
    assert body["errors"] == []

    with app.app_context():
        entry = NomenclatureEntry.query.filter_by(code="PN-1001").first()
        assert entry is not None
        assert entry.manufacturer == "LUZAR"
