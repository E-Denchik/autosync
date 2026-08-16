from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.auth import get_current_user, login_required
from app.extensions import db
from app.models import LaborLine, RepairOrder, ReviewStatus
from app.services.history import log_change

bp = Blueprint("repair_orders_labor", __name__)
bp.before_request(login_required(lambda: None))


def _serialize(line: LaborLine) -> dict:
    threshold = current_app.config["MATCH_CONFIDENCE_THRESHOLD"]
    return {
        "id": line.id,
        "repair_order_id": line.repair_order_id,
        "description": line.description,
        "matched_operation_name": line.matched_operation_name,
        "norm_hours": float(line.norm_hours) if line.norm_hours is not None else None,
        "hourly_rate": float(line.hourly_rate) if line.hourly_rate is not None else None,
        "total_cost": float(line.total_cost) if line.total_cost is not None else None,
        "confidence_level": line.confidence_level.value,
        "confidence_score": line.confidence_score,
        "below_confidence_threshold": line.confidence_score is not None and line.confidence_score < threshold,
        "review_status": line.review_status.value,
        "manually_edited": line.manually_edited,
        "suggested_addition": bool(line.raw_match_data and line.raw_match_data.get("source") == "llm_suggested_addition"),
    }


@bp.get("/<int:repair_order_id>")
def list_labor_lines(repair_order_id: int):
    db.get_or_404(RepairOrder, repair_order_id)
    lines = LaborLine.query.filter_by(repair_order_id=repair_order_id).order_by(LaborLine.id).all()
    serialized = [_serialize(line) for line in lines]
    serialized.sort(
        key=lambda l: (
            l["review_status"] != "pending",
            not l["below_confidence_threshold"],
        )
    )
    return jsonify(serialized)


@bp.patch("/<int:labor_line_id>")
def edit_labor_line(labor_line_id: int):
    line = db.get_or_404(LaborLine, labor_line_id)
    body = request.get_json(force=True) or {}

    if "matched_operation_name" not in body and "norm_hours" not in body:
        return jsonify(error="Нужно указать хотя бы matched_operation_name или norm_hours"), 400

    line.matched_operation_name = body.get("matched_operation_name", line.matched_operation_name)
    if "norm_hours" in body:
        line.norm_hours = body.get("norm_hours")
    if line.norm_hours is not None and line.hourly_rate is not None:
        line.total_cost = float(line.norm_hours) * float(line.hourly_rate)
    line.manually_edited = True
    line.review_status = ReviewStatus.APPROVED
    line.reviewed_at = datetime.utcnow()

    log_change(
        "labor_line",
        line.id,
        "edited",
        actor=get_current_user(),
        details={"matched_operation_name": line.matched_operation_name, "norm_hours": line.norm_hours},
    )
    db.session.commit()
    return jsonify(_serialize(line))


@bp.post("/<int:labor_line_id>/approve")
def approve_labor_line(labor_line_id: int):
    line = db.get_or_404(LaborLine, labor_line_id)
    line.review_status = ReviewStatus.APPROVED
    line.reviewed_at = datetime.utcnow()
    log_change("labor_line", line.id, "approved", actor=get_current_user())
    db.session.commit()
    return jsonify(_serialize(line))


@bp.post("/<int:labor_line_id>/reject")
def reject_labor_line(labor_line_id: int):
    line = db.get_or_404(LaborLine, labor_line_id)
    line.review_status = ReviewStatus.REJECTED
    line.reviewed_at = datetime.utcnow()
    log_change("labor_line", line.id, "rejected", actor=get_current_user())
    db.session.commit()
    return jsonify(_serialize(line))


@bp.post("/bulk")
def bulk_review():
    body = request.get_json(force=True) or {}
    ids = body.get("ids") or []
    action = body.get("action")

    if action not in ("approve", "reject"):
        return jsonify(error="'action' должен быть 'approve' или 'reject'"), 400
    if not ids:
        return jsonify(error="'ids' не может быть пустым"), 400

    status = ReviewStatus.APPROVED if action == "approve" else ReviewStatus.REJECTED
    actor = get_current_user()
    lines = LaborLine.query.filter(LaborLine.id.in_(ids)).all()
    for line in lines:
        line.review_status = status
        line.reviewed_at = datetime.utcnow()
        log_change("labor_line", line.id, status.value, actor=actor)
    db.session.commit()

    return jsonify([_serialize(line) for line in lines])
