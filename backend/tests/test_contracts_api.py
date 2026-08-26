import io
import re
import zipfile

import openpyxl

_FIXED_ZIP_DATE = (2000, 1, 1, 0, 0, 0)
_FIXED_TIMESTAMP = b"2000-01-01T00:00:00Z"


def _xlsx_bytes(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Артикул", "Наименование", "Цена"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return io.BytesIO(_normalize_xlsx(buf.read()))


def _normalize_xlsx(data: bytes) -> bytes:
    """openpyxl всегда пишет "modified" = datetime.now() в docProps/core.xml
    (перезаписывает любое явно заданное значение при save()) и штампует
    КАЖДУЮ запись zip-архива текущим временем — из-за этого два вызова
    _xlsx_bytes() с ОДИНАКОВЫМ содержимым строк, но в разные секунды, дают
    РАЗНЫЕ байты файла и, соответственно, разный content_hash (см.
    app/services/upload_helpers.py). На CI (обычно медленнее локальной
    машины) это реально ловилось: тест на переиспользование договора по
    хэшу файла падал не всегда, а только когда два _xlsx_bytes() в одном
    тесте успевали разъехаться на секунду. Пересобираем zip с фиксированными
    датами записей и нормализованным core.xml, чтобы одно и то же логическое
    содержимое всегда давало один и тот же файл байт-в-байт."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out_buf = io.BytesIO()
    with zipfile.ZipFile(out_buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info in src.infolist():
            content = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                # created/modified оба задаются openpyxl как datetime.now() при
                # save() (явно заданное значение перед save() не переживает его) —
                # нормализуем оба тега, а не только modified.
                content = re.sub(
                    rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
                    lambda m: m.group(1) + _FIXED_TIMESTAMP + m.group(2),
                    content,
                )
            new_info = zipfile.ZipInfo(info.filename, date_time=_FIXED_ZIP_DATE)
            new_info.compress_type = zipfile.ZIP_DEFLATED
            out.writestr(new_info, content)
    return out_buf.getvalue()


def test_xlsx_bytes_helper_is_deterministic_across_time():
    """Регрессия: этот файл падал НЕ ВСЕГДА, а только когда два вызова
    _xlsx_bytes() с одинаковыми строками успевали разъехаться на секунду
    (openpyxl пишет created/modified = datetime.now() в docProps/core.xml
    и штампует каждую запись zip-архива текущим временем) — на CI, обычно
    более медленном, чем локальная машина, это ловилось регулярно (см.
    test_reuploading_the_same_file_reuses_the_parsed_contract_instead_of_duplicating
    ниже, который полагается на content_hash двух отдельно сгенерированных
    файлов с одинаковым содержимым). datetime.now() читает системные часы
    напрямую (не через time.time()), поэтому реальный sleep — единственный
    надёжный способ воспроизвести именно секундный разрыв."""
    import time

    b1 = _xlsx_bytes([["A-1", "Деталь", 100]]).read()
    time.sleep(1.5)
    b2 = _xlsx_bytes([["A-1", "Деталь", 100]]).read()
    assert b1 == b2

    b3 = _xlsx_bytes([["A-2", "Другая деталь", 200]]).read()
    assert b1 != b3


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


def test_reuploading_the_same_file_reuses_the_parsed_contract_instead_of_duplicating(
    client, admin_headers, app, monkeypatch
):
    """Регрессия: заказчик пожаловался, что повторная загрузка того же
    договора создаёт дубликат — теперь при совпадении содержимого файла с
    уже разобранным договором возвращается он же, новый не создаётся."""
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)

    first = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Прайс", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    assert first.status_code == 202
    first_body = first.get_json()
    assert first_body["reused_existing_contract"] is False

    from app.extensions import db
    from app.models import Contract, DocumentProcessingStatus

    with app.app_context():
        contract = db.session.get(Contract, first_body["id"])
        contract.status = DocumentProcessingStatus.PARSED
        db.session.commit()

    second = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Прайс (ещё раз)", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )
    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body["reused_existing_contract"] is True
    assert second_body["id"] == first_body["id"]

    all_contracts = client.get("/api/contracts", headers=admin_headers).get_json()
    assert len(all_contracts) == 1


def test_different_content_is_not_reused(client, admin_headers, app, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)

    first = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Прайс", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    )

    from app.extensions import db
    from app.models import Contract, DocumentProcessingStatus

    with app.app_context():
        contract = db.session.get(Contract, first.get_json()["id"])
        contract.status = DocumentProcessingStatus.PARSED
        db.session.commit()

    second = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Другой прайс", "file": (_xlsx_bytes([["A-2", "Другая деталь", 200]]), "c2.xlsx")},
        content_type="multipart/form-data",
    )
    assert second.status_code == 202
    assert second.get_json()["reused_existing_contract"] is False

    all_contracts = client.get("/api/contracts", headers=admin_headers).get_json()
    assert len(all_contracts) == 2


def test_merge_endpoint_moves_data_and_removes_source(client, admin_headers, app, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)

    source = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Дубликат", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c1.xlsx")},
        content_type="multipart/form-data",
    ).get_json()
    target = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "Основной", "file": (_xlsx_bytes([["A-2", "Другая деталь", 200]]), "c2.xlsx")},
        content_type="multipart/form-data",
    ).get_json()

    resp = client.post(f"/api/contracts/{source['id']}/merge-into/{target['id']}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["contract"]["id"] == target["id"]

    listed = client.get("/api/contracts", headers=admin_headers).get_json()
    assert len(listed) == 1
    assert listed[0]["id"] == target["id"]


def test_merge_endpoint_rejects_unknown_target(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)

    source = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    ).get_json()

    resp = client.post(f"/api/contracts/{source['id']}/merge-into/999999", headers=admin_headers)
    assert resp.status_code == 400


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


def _rates_xlsx(rows):
    import pandas as pd

    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer


def test_import_hourly_rates_file(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)
    contract_id = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    ).get_json()["id"]

    resp = client.post(
        f"/api/contracts/{contract_id}/hourly-rates/import",
        headers=admin_headers,
        data={"file": (_rates_xlsx([{"Марка": "Hyundai", "Ставка": 800}, {"Марка": "Toyota", "Ставка": 900}]), "rates.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"created": 2, "updated": 0, "total": 2}

    listed = client.get(f"/api/contracts/{contract_id}/hourly-rates", headers=admin_headers).get_json()
    assert {r["vehicle_make"]: r["hourly_rate"] for r in listed} == {"Hyundai": 800.0, "Toyota": 900.0}


def test_import_hourly_rates_file_requires_file(client, admin_headers, monkeypatch):
    monkeypatch.setattr("app.api.contracts.enqueue_import_contract", lambda *a, **kw: None)
    contract_id = client.post(
        "/api/contracts",
        headers=admin_headers,
        data={"name": "x", "file": (_xlsx_bytes([["A-1", "Деталь", 100]]), "c.xlsx")},
        content_type="multipart/form-data",
    ).get_json()["id"]

    resp = client.post(f"/api/contracts/{contract_id}/hourly-rates/import", headers=admin_headers, data={})
    assert resp.status_code == 400
