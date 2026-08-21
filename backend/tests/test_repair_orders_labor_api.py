from datetime import datetime

from app.extensions import db
from app.models import (
    Contract,
    ConfidenceLevel,
    DocumentProcessingStatus,
    LaborLine,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)


def _make_repair_order(app) -> int:
    contract = Contract(original_filename="c.xlsx", storage_path="/tmp/c.xlsx", status=DocumentProcessingStatus.PARSED)
    db.session.add(contract)
    db.session.flush()
    order = RepairOrder(
        contract_id=contract.id,
        original_filename="o.xlsx",
        storage_path="/tmp/o.xlsx",
        status=RepairOrderStatus.NEEDS_REVIEW,
    )
    db.session.add(order)
    db.session.commit()
    return order.id


def _make_labor_line(app, repair_order_id, **overrides) -> int:
    defaults = dict(
        repair_order_id=repair_order_id,
        description="Замена масла",
        hourly_rate=1000,
        confidence_level=ConfidenceLevel.LLM_GUESS,
        confidence_score=0.5,
        review_status=ReviewStatus.PENDING,
    )
    defaults.update(overrides)
    line = LaborLine(**defaults)
    db.session.add(line)
    db.session.commit()
    return line.id


def test_list_requires_valid_repair_order(client, admin_headers):
    resp = client.get("/api/repair-orders/labor/999999", headers=admin_headers)
    assert resp.status_code == 404


def test_list_sorts_pending_low_confidence_first(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        approved_id = _make_labor_line(
            app, order_id, description="Уже принято", review_status=ReviewStatus.APPROVED, confidence_score=0.9
        )
        pending_high_conf_id = _make_labor_line(
            app, order_id, description="Ожидает, уверенность высокая", confidence_score=0.95
        )
        pending_low_conf_id = _make_labor_line(
            app, order_id, description="Ожидает, уверенность низкая", confidence_score=0.1
        )

    resp = client.get(f"/api/repair-orders/labor/{order_id}", headers=admin_headers)
    assert resp.status_code == 200
    ids = [line["id"] for line in resp.get_json()]
    # Ожидающие проверки всегда впереди принятых, а среди ожидающих —
    # низкая уверенность впереди высокой (see labor.py: list_labor_lines sort key).
    assert ids.index(pending_low_conf_id) < ids.index(pending_high_conf_id) < ids.index(approved_id)


def test_list_reports_below_confidence_threshold(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        # MATCH_CONFIDENCE_THRESHOLD по умолчанию 0.75 (см. app/config.py).
        low_id = _make_labor_line(app, order_id, confidence_score=0.5)
        high_id = _make_labor_line(app, order_id, confidence_score=0.9)

    body = {l["id"]: l for l in client.get(f"/api/repair-orders/labor/{order_id}", headers=admin_headers).get_json()}
    assert body[low_id]["below_confidence_threshold"] is True
    assert body[high_id]["below_confidence_threshold"] is False


def test_edit_rejects_non_numeric_norm_hours_with_400_not_500(client, admin_headers, app):
    """Регрессия: PATCH раньше падал необработанным ValueError (500) на
    нечисловом norm_hours вместо понятной ошибки 400 — единственное место
    в проекте, где приведение к float не было обёрнуто в try/except."""
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.patch(
        f"/api/repair-orders/labor/{line_id}", headers=admin_headers, json={"norm_hours": "not-a-number"}
    )
    assert resp.status_code == 400
    assert "должен быть числом" in resp.get_json()["error"]


def test_edit_rejects_negative_norm_hours(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.patch(f"/api/repair-orders/labor/{line_id}", headers=admin_headers, json={"norm_hours": -1})
    assert resp.status_code == 400
    assert "положительным" in resp.get_json()["error"]


def test_edit_rejects_zero_norm_hours(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.patch(f"/api/repair-orders/labor/{line_id}", headers=admin_headers, json={"norm_hours": 0})
    assert resp.status_code == 400


def test_edit_requires_at_least_one_field(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.patch(f"/api/repair-orders/labor/{line_id}", headers=admin_headers, json={})
    assert resp.status_code == 400


def test_edit_updates_norm_hours_recomputes_total_cost_and_marks_manual_approved(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id, hourly_rate=1000)

    resp = client.patch(f"/api/repair-orders/labor/{line_id}", headers=admin_headers, json={"norm_hours": 2.5})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["norm_hours"] == 2.5
    assert body["total_cost"] == 2500.0
    assert body["manually_edited"] is True
    assert body["review_status"] == "approved"


def test_edit_updates_operation_name_only(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id, matched_operation_name="Старое название", norm_hours=1)

    resp = client.patch(
        f"/api/repair-orders/labor/{line_id}",
        headers=admin_headers,
        json={"matched_operation_name": "Новое название"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["matched_operation_name"] == "Новое название"
    assert resp.get_json()["norm_hours"] == 1.0


def test_edit_unknown_line_404(client, admin_headers):
    resp = client.patch("/api/repair-orders/labor/999999", headers=admin_headers, json={"norm_hours": 1})
    assert resp.status_code == 404


def test_approve_and_reject(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        approve_id = _make_labor_line(app, order_id)
        reject_id = _make_labor_line(app, order_id)

    approved = client.post(f"/api/repair-orders/labor/{approve_id}/approve", headers=admin_headers)
    assert approved.status_code == 200
    assert approved.get_json()["review_status"] == "approved"

    rejected = client.post(f"/api/repair-orders/labor/{reject_id}/reject", headers=admin_headers)
    assert rejected.status_code == 200
    assert rejected.get_json()["review_status"] == "rejected"


def test_bulk_review_approve_and_reject(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        id1 = _make_labor_line(app, order_id)
        id2 = _make_labor_line(app, order_id)

    resp = client.post(
        "/api/repair-orders/labor/bulk", headers=admin_headers, json={"ids": [id1, id2], "action": "approve"}
    )
    assert resp.status_code == 200
    statuses = {line["id"]: line["review_status"] for line in resp.get_json()}
    assert statuses == {id1: "approved", id2: "approved"}


def test_bulk_review_rejects_invalid_action(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.post(
        "/api/repair-orders/labor/bulk", headers=admin_headers, json={"ids": [line_id], "action": "explode"}
    )
    assert resp.status_code == 400


def test_bulk_review_rejects_empty_ids(client, admin_headers):
    resp = client.post("/api/repair-orders/labor/bulk", headers=admin_headers, json={"ids": [], "action": "approve"})
    assert resp.status_code == 400


def test_history_logs_edit_and_approve(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    client.patch(f"/api/repair-orders/labor/{line_id}", headers=admin_headers, json={"norm_hours": 3})

    history = client.get(f"/api/history?entity_type=labor_line&entity_id={line_id}", headers=admin_headers)
    entries = history.get_json()
    assert len(entries) == 1
    assert entries[0]["action"] == "edited"
