from app.extensions import db
from app.services.history import log_change


def test_history_requires_admin(client, operator_headers):
    resp = client.get("/api/history", headers=operator_headers)
    assert resp.status_code == 403


def test_history_requires_auth(client):
    resp = client.get("/api/history")
    assert resp.status_code == 401


def test_history_lists_entries(client, admin_headers, app):
    with app.app_context():
        log_change("widget", 1, "created")
        log_change("widget", 1, "approved")
        db.session.commit()

    resp = client.get("/api/history", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body) == 2
    # самая свежая запись первая
    assert body[0]["action"] == "approved"
    assert body[0]["end_day"] is None
    assert body[1]["action"] == "created"
    assert body[1]["end_day"] is not None


def test_history_filters_by_entity_type_and_action(client, admin_headers, app):
    with app.app_context():
        log_change("widget", 1, "created")
        log_change("gadget", 2, "created")
        db.session.commit()

    resp = client.get("/api/history?entity_type=gadget", headers=admin_headers)
    body = resp.get_json()
    assert len(body) == 1
    assert body[0]["entity_type"] == "gadget"


def test_history_entity_types_endpoint(client, admin_headers, app):
    with app.app_context():
        log_change("widget", 1, "created")
        log_change("gadget", 2, "created")
        db.session.commit()

    resp = client.get("/api/history/entity-types", headers=admin_headers)
    assert resp.status_code == 200
    assert set(resp.get_json()) == {"widget", "gadget"}


def test_approving_a_match_creates_history_entry(client, admin_headers, app):
    from app.models import Contract, ConfidenceLevel, DocumentProcessingStatus, PartMatch, RepairOrder, RepairOrderStatus, ReviewStatus

    with app.app_context():
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
        db.session.flush()
        match = PartMatch(
            repair_order_id=order.id,
            contract_article="A1",
            contract_name="Деталь",
            confidence_level=ConfidenceLevel.EXACT,
            review_status=ReviewStatus.PENDING,
        )
        db.session.add(match)
        db.session.commit()
        match_id = match.id

    resp = client.post(f"/api/repair-orders/matching/{match_id}/approve", headers=admin_headers)
    assert resp.status_code == 200

    history_resp = client.get(f"/api/history?entity_type=part_match&entity_id={match_id}", headers=admin_headers)
    body = history_resp.get_json()
    assert any(e["action"] == "approved" for e in body)
    assert body[0]["actor_email"] == "admin@test.local"
