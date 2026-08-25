from datetime import datetime

import pytest

from app.extensions import db
from app.models import (
    Contract,
    Contragent,
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


def test_list_exposes_cross_make_estimate(client, admin_headers, app):
    with app.app_context():
        repair_order_id = _make_repair_order(app)
        _make_labor_line(
            app,
            repair_order_id,
            norm_hours=0.5,
            raw_match_data={
                "source": "llm_fallback_cross_make",
                "reasoning": "похожая операция",
                "estimate_from_make": "TOYOTA",
                "estimate_from_model": None,
            },
        )

    body = client.get(f"/api/repair-orders/labor/{repair_order_id}", headers=admin_headers).get_json()
    assert body[0]["cross_make_estimate"] == {"from_make": "TOYOTA", "from_model": None}


def test_list_cross_make_estimate_is_none_for_ordinary_llm_guess(client, admin_headers, app):
    with app.app_context():
        repair_order_id = _make_repair_order(app)
        _make_labor_line(
            app,
            repair_order_id,
            norm_hours=0.5,
            raw_match_data={"source": "llm_fallback", "reasoning": "обычное совпадение"},
        )

    body = client.get(f"/api/repair-orders/labor/{repair_order_id}", headers=admin_headers).get_json()
    assert body[0]["cross_make_estimate"] is None


def test_list_exposes_llm_error_so_reviewer_can_tell_it_apart_from_genuine_no_match(client, admin_headers, app):
    """Регрессия по прозрачности: раньше "ИИ была недоступна" и "ИИ честно
    не нашла совпадение" выглядели для проверяющего одинаково — просто
    "не найдено" без единой подсказки, что дело в самом сервисе, а не в
    данных."""
    with app.app_context():
        repair_order_id = _make_repair_order(app)
        _make_labor_line(
            app,
            repair_order_id,
            norm_hours=None,
            confidence_score=0.0,
            raw_match_data={"source": "llm_error", "error": "llm-service недоступен: Connection refused"},
        )

    body = client.get(f"/api/repair-orders/labor/{repair_order_id}", headers=admin_headers).get_json()
    assert body[0]["llm_error"] == "llm-service недоступен: Connection refused"


def test_suggested_addition_fires_for_contract_catalog_source_too(client, admin_headers, app):
    """Регрессия: раньше suggested_addition проверял только источник
    "llm_suggested_addition" — для контрактов со своим каталогом нормо-часов
    реальный источник "llm_suggested_addition_contract_catalog", и флаг
    никогда не срабатывал в этом (частом) случае."""
    with app.app_context():
        repair_order_id = _make_repair_order(app)
        _make_labor_line(
            app,
            repair_order_id,
            norm_hours=1.0,
            raw_match_data={"source": "llm_suggested_addition_contract_catalog", "reasoning": "обычно идёт вместе"},
        )

    body = client.get(f"/api/repair-orders/labor/{repair_order_id}", headers=admin_headers).get_json()
    assert body[0]["suggested_addition"] is True


@pytest.mark.parametrize(
    "raw_match_data,confidence_level,norm_hours,expected_category",
    [
        (None, "exact", 1.0, "exact"),
        ({"source": "llm_error", "error": "x"}, "llm_guess", None, "llm_error"),
        ({"source": "llm_fallback_cross_make"}, "llm_guess", 1.0, "cross_make_estimate"),
        ({"source": "llm_fallback_cross_make_contract_catalog"}, "llm_guess", 1.0, "cross_make_estimate"),
        ({"source": "llm_suggested_addition"}, "llm_guess", 1.0, "suggested_addition"),
        ({"source": "llm_suggested_addition_contract_catalog"}, "llm_guess", 1.0, "suggested_addition"),
        ({"source": "repair_order_stated_value"}, "llm_guess", 1.0, "from_repair_order"),
        ({"source": "no_match_found"}, "llm_guess", None, "no_match"),
        ({"source": "llm_fallback"}, "llm_guess", 1.0, "llm_guess"),
    ],
)
def test_match_category_classification(
    client, admin_headers, app, raw_match_data, confidence_level, norm_hours, expected_category
):
    from app.models import ConfidenceLevel

    with app.app_context():
        repair_order_id = _make_repair_order(app)
        _make_labor_line(
            app,
            repair_order_id,
            norm_hours=norm_hours,
            confidence_level=ConfidenceLevel(confidence_level),
            raw_match_data=raw_match_data,
        )

    body = client.get(f"/api/repair-orders/labor/{repair_order_id}", headers=admin_headers).get_json()
    assert body[0]["match_category"] == expected_category


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
        approve_id = _make_labor_line(app, order_id, norm_hours=1.5)
        reject_id = _make_labor_line(app, order_id)

    approved = client.post(f"/api/repair-orders/labor/{approve_id}/approve", headers=admin_headers)
    assert approved.status_code == 200
    assert approved.get_json()["review_status"] == "approved"

    rejected = client.post(f"/api/repair-orders/labor/{reject_id}/reject", headers=admin_headers)
    assert rejected.status_code == 200
    assert rejected.get_json()["review_status"] == "rejected"


def test_approve_rejects_line_without_norm_hours(client, admin_headers, app):
    """Регрессия по реальным данным заказчика: работу без нормы часов можно
    было принять как есть, и она молча уезжала в итоговый xlsx с нулевой
    суммой ("Итого работы: 0") — заказчик замечал это только в готовом
    документе."""
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.post(f"/api/repair-orders/labor/{line_id}/approve", headers=admin_headers)
    assert resp.status_code == 409

    with app.app_context():
        line = db.session.get(LaborLine, line_id)
        assert line.review_status == ReviewStatus.PENDING


def test_bulk_review_approve_and_reject(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        id1 = _make_labor_line(app, order_id, norm_hours=1.0)
        id2 = _make_labor_line(app, order_id, norm_hours=2.0)

    resp = client.post(
        "/api/repair-orders/labor/bulk", headers=admin_headers, json={"ids": [id1, id2], "action": "approve"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["skipped"] == []
    statuses = {line["id"]: line["review_status"] for line in body["updated"]}
    assert statuses == {id1: "approved", id2: "approved"}


def test_bulk_review_skips_lines_without_norm_hours_but_approves_the_rest(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        ok_id = _make_labor_line(app, order_id, description="Замена масла", norm_hours=1.0)
        missing_id = _make_labor_line(app, order_id, description="Опора ДВС правая замена")

    resp = client.post(
        "/api/repair-orders/labor/bulk",
        headers=admin_headers,
        json={"ids": [ok_id, missing_id], "action": "approve"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert [line["id"] for line in body["updated"]] == [ok_id]
    assert body["skipped"] == [{"id": missing_id, "description": "Опора ДВС правая замена", "reason": "Не указана норма часов"}]

    with app.app_context():
        assert db.session.get(LaborLine, ok_id).review_status == ReviewStatus.APPROVED
        assert db.session.get(LaborLine, missing_id).review_status == ReviewStatus.PENDING


def test_bulk_review_reject_does_not_require_norm_hours(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)
        line_id = _make_labor_line(app, order_id)

    resp = client.post(
        "/api/repair-orders/labor/bulk", headers=admin_headers, json={"ids": [line_id], "action": "reject"}
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["skipped"] == []
    assert body["updated"][0]["review_status"] == "rejected"


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


def test_add_labor_line_creates_new_approved_line_with_resolved_rate(client, admin_headers, app):
    """Ручное добавление строки работ (см. matching.py::add_part — тот же
    принцип для запчастей) — заказчик просил свободную форму добавления,
    когда ни каталог, ни AutoData операцию не нашли ни по одной марке."""
    with app.app_context():
        contragent = Contragent(name="СТО Восток", hourly_rate=1500)
        db.session.add(contragent)
        db.session.flush()
        contract = Contract(original_filename="c.xlsx", storage_path="/tmp/c.xlsx", status=DocumentProcessingStatus.PARSED)
        db.session.add(contract)
        db.session.flush()
        order = RepairOrder(
            contract_id=contract.id,
            contragent_id=contragent.id,
            original_filename="o.xlsx",
            storage_path="/tmp/o.xlsx",
            status=RepairOrderStatus.NEEDS_REVIEW,
        )
        db.session.add(order)
        db.session.commit()
        order_id = order.id

    resp = client.post(
        f"/api/repair-orders/labor/{order_id}",
        headers=admin_headers,
        json={"matched_operation_name": "Замена ремня ГРМ", "norm_hours": 2.5},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["matched_operation_name"] == "Замена ремня ГРМ"
    assert float(body["norm_hours"]) == 2.5
    assert float(body["hourly_rate"]) == 1500
    assert float(body["total_cost"]) == 3750
    assert body["review_status"] == "approved"
    assert body["manually_edited"] is True

    listed = client.get(f"/api/repair-orders/labor/{order_id}", headers=admin_headers)
    assert len(listed.get_json()) == 1


def test_add_labor_line_requires_operation_name_and_positive_hours(client, admin_headers, app):
    with app.app_context():
        order_id = _make_repair_order(app)

    missing_name = client.post(
        f"/api/repair-orders/labor/{order_id}", headers=admin_headers, json={"norm_hours": 1}
    )
    assert missing_name.status_code == 400

    bad_hours = client.post(
        f"/api/repair-orders/labor/{order_id}",
        headers=admin_headers,
        json={"matched_operation_name": "Диагностика", "norm_hours": 0},
    )
    assert bad_hours.status_code == 400


def test_add_labor_line_requires_valid_repair_order(client, admin_headers):
    resp = client.post(
        "/api/repair-orders/labor/999999",
        headers=admin_headers,
        json={"matched_operation_name": "Диагностика", "norm_hours": 1},
    )
    assert resp.status_code == 404
