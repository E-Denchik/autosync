import io
from unittest.mock import MagicMock

import pandas as pd

from app.extensions import db
from app.models import BrandAlias


def _xlsx_bytes(rows):
    """rows — список (alias, canonical|None). Пишем с шапкой (первая строка
    файла — заголовки колонок) — ровно то, что _read_two_columns ожидает
    (header=0, пропускает первую строку)."""
    buffer = io.BytesIO()
    pd.DataFrame(rows, columns=["Марка", "Каноничная марка"]).to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)
    return buffer


def test_create_list_update_delete_alias(client, admin_headers):
    create_resp = client.post(
        "/api/brand-aliases", headers=admin_headers, json={"alias": "Тестомарка", "canonical_make": "testbrand"}
    )
    assert create_resp.status_code == 201
    body = create_resp.get_json()
    assert body["alias"] == "Тестомарка"
    assert body["canonical_make"] == "TESTBRAND"  # приводим к верхнему регистру
    assert body["source"] == "manual"
    entry_id = body["id"]

    # per_page побольше — справочник уже засеян builtin-записями (см.
    # conftest.py), дефолтная страница по алфавиту может не захватить
    # новую запись где-то в середине.
    list_resp = client.get("/api/brand-aliases?per_page=200", headers=admin_headers)
    assert any(e["id"] == entry_id for e in list_resp.get_json())

    search_resp = client.get("/api/brand-aliases?q=Тестомарка", headers=admin_headers)
    assert any(e["id"] == entry_id for e in search_resp.get_json())

    update_resp = client.patch(
        f"/api/brand-aliases/{entry_id}", headers=admin_headers, json={"canonical_make": "renamed"}
    )
    assert update_resp.status_code == 200
    assert update_resp.get_json()["canonical_make"] == "RENAMED"

    delete_resp = client.delete(f"/api/brand-aliases/{entry_id}", headers=admin_headers)
    assert delete_resp.status_code == 204


def test_create_requires_alias(client, admin_headers):
    resp = client.post("/api/brand-aliases", headers=admin_headers, json={"canonical_make": "X"})
    assert resp.status_code == 400


def test_create_rejects_duplicate_alias_case_insensitive(client, admin_headers):
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Дубль", "canonical_make": "A"})
    resp = client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "дубль", "canonical_make": "B"})
    assert resp.status_code == 409


def test_list_filters_unresolved(client, admin_headers):
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Полная", "canonical_make": "FULL"})
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Пустая"})

    resp = client.get("/api/brand-aliases?unresolved=1", headers=admin_headers)
    aliases = {e["alias"] for e in resp.get_json()}
    assert "Пустая" in aliases
    assert "Полная" not in aliases


def test_upload_creates_entries_with_and_without_canonical_column(client, admin_headers, app):
    rows = [["Новая марка", "NEWBRAND"], ["Марка без каноники", None]]
    resp = client.post(
        "/api/brand-aliases/upload",
        headers=admin_headers,
        data={"file": (_xlsx_bytes(rows), "brands.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201
    assert resp.get_json()["created"] == 2

    with app.app_context():
        full = BrandAlias.query.filter_by(alias="Новая марка").first()
        assert full.canonical_make == "NEWBRAND"
        assert full.source == "upload"

        empty = BrandAlias.query.filter_by(alias="Марка без каноники").first()
        assert empty.canonical_make is None


def test_upload_does_not_overwrite_existing_canonical_with_empty(client, admin_headers, app):
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Уже есть", "canonical_make": "KEEPME"})

    rows = [["Уже есть", None]]
    resp = client.post(
        "/api/brand-aliases/upload",
        headers=admin_headers,
        data={"file": (_xlsx_bytes(rows), "brands.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 201

    with app.app_context():
        entry = BrandAlias.query.filter_by(alias="Уже есть").first()
        assert entry.canonical_make == "KEEPME"  # не затёрто пустой ячейкой


def test_upload_rejects_unsupported_extension(client, admin_headers):
    resp = client.post(
        "/api/brand-aliases/upload",
        headers=admin_headers,
        data={"file": (io.BytesIO(b"x"), "brands.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_normalize_calls_llm_only_for_unresolved_and_saves_result(client, admin_headers, app, monkeypatch):
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Известная", "canonical_make": "KNOWN"})
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Неизвестная"})

    fake_llm = MagicMock()
    fake_llm.normalize_brand_labels.return_value = {"Неизвестная": "RESOLVED"}
    monkeypatch.setattr("app.api.brand_aliases.LLMClient", lambda *a, **kw: fake_llm)

    resp = client.post("/api/brand-aliases/normalize", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"normalized": 1, "total": 1}

    fake_llm.normalize_brand_labels.assert_called_once_with(["Неизвестная"])

    with app.app_context():
        entry = BrandAlias.query.filter_by(alias="Неизвестная").first()
        assert entry.canonical_make == "RESOLVED"
        assert entry.source == "llm"


def test_normalize_with_nothing_unresolved_does_not_call_llm(client, admin_headers, monkeypatch):
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Известная", "canonical_make": "KNOWN"})

    fake_llm = MagicMock()
    monkeypatch.setattr("app.api.brand_aliases.LLMClient", lambda *a, **kw: fake_llm)

    resp = client.post("/api/brand-aliases/normalize", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {"normalized": 0, "total": 0}
    fake_llm.normalize_brand_labels.assert_not_called()


def test_normalize_returns_502_when_llm_unavailable(client, admin_headers, monkeypatch):
    client.post("/api/brand-aliases", headers=admin_headers, json={"alias": "Неизвестная"})

    fake_llm = MagicMock()
    fake_llm.normalize_brand_labels.side_effect = RuntimeError("недоступен")
    monkeypatch.setattr("app.api.brand_aliases.LLMClient", lambda *a, **kw: fake_llm)

    resp = client.post("/api/brand-aliases/normalize", headers=admin_headers)
    assert resp.status_code == 502
