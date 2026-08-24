import os

TESTDATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "testdata")


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


def _rates_xlsx(rows):
    import io

    import pandas as pd

    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer


def test_import_hourly_rates_creates_rows_from_file(client, admin_headers):
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "Управление дорог", "hourly_rate": 1000}
    ).get_json()["id"]

    resp = client.post(
        f"/api/contragents/{contragent_id}/hourly-rates/import",
        headers=admin_headers,
        data={"file": (_rates_xlsx([{"Марка": "Hyundai", "Ставка": 800}, {"Марка": "Toyota", "Ставка": 900}]), "rates.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"created": 2, "updated": 0, "total": 2}

    listed = client.get(f"/api/contragents/{contragent_id}/hourly-rates", headers=admin_headers).get_json()
    by_make = {r["vehicle_make"]: r["hourly_rate"] for r in listed}
    assert by_make == {"Hyundai": 800.0, "Toyota": 900.0}


def test_import_hourly_rates_updates_existing_make_instead_of_duplicating(client, admin_headers):
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "Управление дорог", "hourly_rate": 1000}
    ).get_json()["id"]
    client.post(
        f"/api/contragents/{contragent_id}/hourly-rates",
        headers=admin_headers,
        json={"vehicle_make": "HYUNDAI", "hourly_rate": 700},
    )

    resp = client.post(
        f"/api/contragents/{contragent_id}/hourly-rates/import",
        headers=admin_headers,
        # Другой регистр в файле — должно найти и обновить ту же марку, не завести вторую.
        data={"file": (_rates_xlsx([{"Марка": "Hyundai", "Ставка": 800}]), "rates.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.get_json() == {"created": 0, "updated": 1, "total": 1}

    listed = client.get(f"/api/contragents/{contragent_id}/hourly-rates", headers=admin_headers).get_json()
    assert len(listed) == 1
    assert listed[0]["hourly_rate"] == 800.0


def test_import_hourly_rates_requires_file(client, admin_headers):
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "СТО Юг", "hourly_rate": 1000}
    ).get_json()["id"]
    resp = client.post(f"/api/contragents/{contragent_id}/hourly-rates/import", headers=admin_headers, data={})
    assert resp.status_code == 400


def test_import_hourly_rates_reports_parse_error_for_unrecognized_columns(client, admin_headers):
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "СТО Север", "hourly_rate": 1000}
    ).get_json()["id"]
    resp = client.post(
        f"/api/contragents/{contragent_id}/hourly-rates/import",
        headers=admin_headers,
        data={"file": (_rates_xlsx([{"Column A": "x", "Column B": 1}]), "rates.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_import_hourly_rates_accepts_real_customer_docx_file(client, admin_headers):
    """Реальный файл заказчика — приложение к тендерному контракту (.docx,
    не Excel), марка+модель одной ячейкой, несколько моделей через запятую
    на одну ставку, плюс итоговая строка. Должен полностью пройти через
    HTTP-эндпоинт, а не только через сервисную функцию напрямую."""
    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "Управление дорог", "hourly_rate": 1000}
    ).get_json()["id"]

    with open(os.path.join(TESTDATA_DIR, "Нормочасы.docx"), "rb") as f:
        resp = client.post(
            f"/api/contragents/{contragent_id}/hourly-rates/import",
            headers=admin_headers,
            data={"file": (f, "Нормочасы.docx")},
            content_type="multipart/form-data",
        )
    assert resp.status_code == 200
    assert resp.get_json() == {"created": 15, "updated": 0, "total": 15}

    listed = client.get(f"/api/contragents/{contragent_id}/hourly-rates", headers=admin_headers).get_json()
    by_model = {(r["vehicle_make"], r["vehicle_model"]): r["hourly_rate"] for r in listed}
    assert by_model[("Hyundai", "IX35")] == 810.0
    assert by_model[("Hyundai", "Accent")] == 720.0
    assert not any("итого" in make.lower() for make, _ in by_model)


def test_import_hourly_rates_accepts_a_photo_of_the_rate_table(client, admin_headers, monkeypatch):
    """Тот же реальный тендерный прайс, но пришедший как фото/скан, а не
    цифровой файл — бумажные приложения к контрактам вполне могут прийти
    именно так. Идёт через OCR + LLM (см. document_parser._parse_rate_table_via_ocr)."""
    import io

    from PIL import Image

    monkeypatch.setattr(
        "pytesseract.image_to_string",
        lambda image, lang=None: "Chevrolet Niva 540\nHyundai Tucson, Hyundai IX35 810\n",
    )
    monkeypatch.setattr(
        "app.services.llm_client.LLMClient.extract_table_from_text",
        lambda self, raw_text, fields: [
            {"vehicle_make": "Chevrolet Niva", "vehicle_model": None, "hourly_rate": 540},
            {"vehicle_make": "Hyundai Tucson, Hyundai IX35", "vehicle_model": None, "hourly_rate": 810},
        ],
    )

    contragent_id = client.post(
        "/api/contragents", headers=admin_headers, json={"name": "Управление дорог", "hourly_rate": 1000}
    ).get_json()["id"]

    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    buf.seek(0)

    resp = client.post(
        f"/api/contragents/{contragent_id}/hourly-rates/import",
        headers=admin_headers,
        data={"file": (buf, "rates.png")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"created": 3, "updated": 0, "total": 3}

    listed = client.get(f"/api/contragents/{contragent_id}/hourly-rates", headers=admin_headers).get_json()
    by_model = {(r["vehicle_make"], r["vehicle_model"]): r["hourly_rate"] for r in listed}
    assert by_model[("Hyundai", "IX35")] == 810.0
