import pytest

from app.extensions import db
from app.models import (
    Contract,
    ConfidenceLevel,
    DocumentProcessingStatus,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)


@pytest.fixture
def repair_order_with_matches(app):
    with app.app_context():
        contract = Contract(
            original_filename="contract.xlsx",
            storage_path="/tmp/contract.xlsx",
            status=DocumentProcessingStatus.PARSED,
        )
        db.session.add(contract)
        db.session.flush()

        order = RepairOrder(
            contract_id=contract.id,
            original_filename="order.xlsx",
            storage_path="/tmp/order.xlsx",
            status=RepairOrderStatus.NEEDS_REVIEW,
            parsed_lines=[{"article": "ABC-1", "name": "Диск", "qty": 1, "price": 1000.0}],
        )
        db.session.add(order)
        db.session.flush()

        m1 = PartMatch(
            repair_order_id=order.id,
            contract_article="ABC-1",
            contract_name="Тормозной диск",
            matched_article="ABC-1",
            matched_name="Диск тормозной",
            matched_price=1000.0,
            confidence_level=ConfidenceLevel.EXACT,
            confidence_score=1.0,
            review_status=ReviewStatus.PENDING,
        )
        m2 = PartMatch(
            repair_order_id=order.id,
            contract_article="XYZ-9",
            contract_name="Фильтр",
            matched_article=None,
            matched_name=None,
            confidence_level=ConfidenceLevel.LLM_GUESS,
            confidence_score=0.4,
            review_status=ReviewStatus.PENDING,
        )
        db.session.add_all([m1, m2])
        db.session.commit()
        return {"order_id": order.id, "match_ids": [m1.id, m2.id]}


def test_list_matches(client, admin_headers, repair_order_with_matches):
    order_id = repair_order_with_matches["order_id"]
    resp = client.get(f"/api/repair-orders/matching/{order_id}", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 2
    assert {m["confidence_level"] for m in body} == {"exact", "llm_guess"}


def test_list_candidates_returns_parsed_lines(client, admin_headers, repair_order_with_matches):
    order_id = repair_order_with_matches["order_id"]
    resp = client.get(
        f"/api/repair-orders/matching/{order_id}/candidates", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.get_json() == [{"article": "ABC-1", "name": "Диск", "qty": 1, "price": 1000.0}]


def test_edit_match_marks_manually_edited_and_approved(client, admin_headers, repair_order_with_matches, app):
    match_id = repair_order_with_matches["match_ids"][1]
    resp = client.patch(
        f"/api/repair-orders/matching/{match_id}",
        headers=admin_headers,
        json={"matched_article": "XYZ-9-ALT", "matched_name": "Фильтр альтернативный"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["manually_edited"] is True
    assert body["review_status"] == "approved"
    assert body["matched_article"] == "XYZ-9-ALT"


def test_edit_match_requires_article_or_name(client, admin_headers, repair_order_with_matches):
    match_id = repair_order_with_matches["match_ids"][0]
    resp = client.patch(
        f"/api/repair-orders/matching/{match_id}", headers=admin_headers, json={}
    )
    assert resp.status_code == 400


def test_approve_and_reject_match(client, admin_headers, repair_order_with_matches):
    m1, m2 = repair_order_with_matches["match_ids"]

    approve_resp = client.post(
        f"/api/repair-orders/matching/{m1}/approve", headers=admin_headers
    )
    assert approve_resp.get_json()["review_status"] == "approved"

    reject_resp = client.post(f"/api/repair-orders/matching/{m2}/reject", headers=admin_headers)
    assert reject_resp.get_json()["review_status"] == "rejected"


def test_bulk_review(client, admin_headers, repair_order_with_matches):
    ids = repair_order_with_matches["match_ids"]
    resp = client.post(
        "/api/repair-orders/matching/bulk",
        headers=admin_headers,
        json={"ids": ids, "action": "approve"},
    )
    assert resp.status_code == 200
    assert all(m["review_status"] == "approved" for m in resp.get_json())


def test_bulk_review_validates_action(client, admin_headers, repair_order_with_matches):
    resp = client.post(
        "/api/repair-orders/matching/bulk",
        headers=admin_headers,
        json={"ids": repair_order_with_matches["match_ids"], "action": "explode"},
    )
    assert resp.status_code == 400


def test_export_csv(client, admin_headers, repair_order_with_matches):
    order_id = repair_order_with_matches["order_id"]
    resp = client.get(
        f"/api/repair-orders/matching/{order_id}/export", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    text = resp.get_data(as_text=True)
    assert "ABC-1" in text
    assert "XYZ-9" in text


def test_generate_document_blocked_while_pending(client, admin_headers, repair_order_with_matches):
    order_id = repair_order_with_matches["order_id"]
    resp = client.post(
        f"/api/repair-orders/matching/{order_id}/generate-document", headers=admin_headers
    )
    assert resp.status_code == 409


def test_generate_document_succeeds_once_all_reviewed(
    client, admin_headers, repair_order_with_matches, tmp_path, app
):
    order_id = repair_order_with_matches["order_id"]

    with app.app_context():
        order = db.session.get(RepairOrder, order_id)
        order.storage_path = str(tmp_path / "order.xlsx")
        db.session.commit()

    client.post(
        "/api/repair-orders/matching/bulk",
        headers=admin_headers,
        json={"ids": repair_order_with_matches["match_ids"], "action": "approve"},
    )

    resp = client.post(
        f"/api/repair-orders/matching/{order_id}/generate-document", headers=admin_headers
    )
    assert resp.status_code == 200
    assert resp.mimetype in (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    )

    with app.app_context():
        order = db.session.get(RepairOrder, order_id)
        # Регрессия: RepairOrderStatus.REVIEWED никогда не выставлялся —
        # заказ-наряд навсегда оставался needs_review даже после генерации
        # документа, засоряя счётчик "нужно проверить" на дашборде.
        assert order.status == RepairOrderStatus.REVIEWED
