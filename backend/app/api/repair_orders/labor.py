from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import ConfidenceLevel, LaborLine, RepairOrder, ReviewStatus
from app.services.confidence_display import is_verified
from app.services.history import log_change
from app.services.repair_order_processor import resolve_hourly_rate

bp = Blueprint("repair_orders_labor", __name__)


_SUGGESTED_ADDITION_SOURCES = ("llm_suggested_addition", "llm_suggested_addition_contract_catalog")
_CROSS_MAKE_SOURCES = ("llm_fallback_cross_make", "llm_fallback_cross_make_contract_catalog")


def _labor_category(line: LaborLine) -> str:
    """Единая категория того, откуда взялась норма часов — см. тот же
    комментарий у _match_category в api/repair_orders/matching.py."""
    source = (line.raw_match_data or {}).get("source")
    if line.confidence_level.value == "exact":
        return "exact"
    if source == "llm_error":
        return "llm_error"
    if source in _CROSS_MAKE_SOURCES:
        return "cross_make_estimate"
    if source in _SUGGESTED_ADDITION_SOURCES:
        return "suggested_addition"
    if source == "repair_order_stated_value":
        return "from_repair_order"
    if line.norm_hours is None:
        return "no_match"
    return "llm_guess"


def _serialize(line: LaborLine) -> dict:
    threshold = current_app.config["MATCH_CONFIDENCE_THRESHOLD"]
    category = _labor_category(line)
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
        # См. тот же комментарий в api/repair_orders/matching.py::_serialize.
        "is_verified": is_verified(
            match_category=category,
            confidence_score=line.confidence_score,
            review_status=line.review_status.value,
            manually_edited=line.manually_edited,
            threshold=threshold,
            has_value=line.norm_hours is not None,
        ),
        "review_status": line.review_status.value,
        "manually_edited": line.manually_edited,
        # Регрессия: раньше проверялся только один из двух возможных
        # источников ("llm_suggested_addition") — для контрактов со своим
        # каталогом нормо-часов реальный источник
        # "llm_suggested_addition_contract_catalog", и флаг никогда не
        # срабатывал в этом (частом) случае.
        "suggested_addition": bool(
            line.raw_match_data and line.raw_match_data.get("source") in _SUGGESTED_ADDITION_SOURCES
        ),
        # Норма часов не подтверждена каталогом (matched_operation_name всё
        # ещё пуст), но взята из самого заказ-наряда, а не выдумана — фронт
        # должен это показать иначе, чем просто пустую норму.
        "norm_hours_from_repair_order": bool(
            line.raw_match_data and line.raw_match_data.get("source") == "repair_order_stated_value"
        ),
        # Точной марки в справочнике/каталоге контракта не нашлось вовсе —
        # LLM перенесла норму с операции по ДРУГОЙ марке (см. labor_matcher.py:
        # find_norm_hours_any_make/_contract_labor_candidates_any_make).
        # Менее надёжно, чем обычная LLM-догадка по своей марке — фронт
        # должен явно это показать, а не просто "догадка LLM".
        "cross_make_estimate": (
            {
                "from_make": line.raw_match_data.get("estimate_from_make"),
                "from_model": line.raw_match_data.get("estimate_from_model"),
            }
            if line.raw_match_data and line.raw_match_data.get("source") in _CROSS_MAKE_SOURCES
            else None
        ),
        # См. тот же комментарий в api/repair_orders/matching.py — отличает
        # "ИИ честно не нашла совпадение" от "ИИ вообще была недоступна".
        "llm_error": (
            line.raw_match_data.get("error")
            if line.raw_match_data and line.raw_match_data.get("source") == "llm_error"
            else None
        ),
        "match_category": category,
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


@bp.post("/<int:repair_order_id>")
def add_labor_line(repair_order_id: int):
    """Добавляет НОВУЮ строку работ вручную — например, операцию, которую
    ни каталог договора, ни AutoData не нашли ни по одной марке (см.
    labor_matcher.py). Сразу approved: раз оператор осознанно вписал
    операцию и часы, дальнейшего подтверждения не нужно (тот же принцип,
    что и в matching.py::add_part)."""
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    body = request.get_json(force=True) or {}

    operation_name = (body.get("matched_operation_name") or "").strip()
    if not operation_name:
        return jsonify(error="'matched_operation_name' обязателен"), 400
    try:
        norm_hours = float(body.get("norm_hours"))
    except (TypeError, ValueError):
        return jsonify(error="'norm_hours' должен быть числом"), 400
    if norm_hours <= 0:
        return jsonify(error="'norm_hours' должен быть положительным"), 400

    hourly_rate = resolve_hourly_rate(repair_order)
    total_cost = norm_hours * hourly_rate if hourly_rate is not None else None

    line = LaborLine(
        repair_order_id=repair_order_id,
        description=operation_name,
        matched_operation_name=operation_name,
        norm_hours=norm_hours,
        hourly_rate=hourly_rate,
        total_cost=total_cost,
        confidence_level=ConfidenceLevel.EXACT,
        confidence_score=1.0,
        review_status=ReviewStatus.APPROVED,
        manually_edited=True,
        reviewed_at=datetime.utcnow(),
        raw_match_data={"source": "manual_add"},
    )
    db.session.add(line)
    db.session.flush()
    log_change(
        "labor_line",
        line.id,
        "created",
        details={"matched_operation_name": operation_name, "norm_hours": norm_hours, "source": "manual_add"},
    )
    db.session.commit()
    return jsonify(_serialize(line)), 201


@bp.patch("/<int:labor_line_id>")
def edit_labor_line(labor_line_id: int):
    line = db.get_or_404(LaborLine, labor_line_id)
    body = request.get_json(force=True) or {}

    if "matched_operation_name" not in body and "norm_hours" not in body:
        return jsonify(error="Нужно указать хотя бы matched_operation_name или norm_hours"), 400

    if "norm_hours" in body:
        raw_norm_hours = body.get("norm_hours")
        try:
            norm_hours = float(raw_norm_hours)
        except (TypeError, ValueError):
            return jsonify(error="'norm_hours' должен быть числом"), 400
        if norm_hours <= 0:
            return jsonify(error="'norm_hours' должен быть положительным"), 400
        line.norm_hours = norm_hours

    line.matched_operation_name = body.get("matched_operation_name", line.matched_operation_name)
    if line.norm_hours is not None and line.hourly_rate is not None:
        line.total_cost = float(line.norm_hours) * float(line.hourly_rate)
    line.manually_edited = True
    line.review_status = ReviewStatus.APPROVED
    line.reviewed_at = datetime.utcnow()

    log_change(
        "labor_line",
        line.id,
        "edited",
        details={
            "matched_operation_name": line.matched_operation_name,
            # line.norm_hours — SQLAlchemy Numeric, приходит как Decimal при
            # чтении уже сохранённой строки (не только что присвоенный
            # float выше) — Decimal не сериализуется в JSON для колонки details.
            "norm_hours": float(line.norm_hours) if line.norm_hours is not None else None,
        },
    )
    db.session.commit()
    return jsonify(_serialize(line))


@bp.post("/<int:labor_line_id>/approve")
def approve_labor_line(labor_line_id: int):
    line = db.get_or_404(LaborLine, labor_line_id)
    if line.norm_hours is None:
        # Регрессия по реальным данным заказчика: работу без нормы часов
        # раньше можно было принять как есть — она молча уезжала в итоговый
        # xlsx с пустой нормой и нулевой суммой ("Итого работы: 0"),
        # заказчик замечал это только в готовом документе. Норму нужно
        # сначала проставить через PATCH (правку) или отклонить работу.
        return (
            jsonify(error="Сначала укажите норму часов — без неё работа не попадёт в итоговый документ"),
            409,
        )
    line.review_status = ReviewStatus.APPROVED
    line.reviewed_at = datetime.utcnow()
    log_change("labor_line", line.id, "approved")
    db.session.commit()
    return jsonify(_serialize(line))


@bp.post("/<int:labor_line_id>/reject")
def reject_labor_line(labor_line_id: int):
    line = db.get_or_404(LaborLine, labor_line_id)
    line.review_status = ReviewStatus.REJECTED
    line.reviewed_at = datetime.utcnow()
    log_change("labor_line", line.id, "rejected")
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

    lines = LaborLine.query.filter(LaborLine.id.in_(ids)).all()

    if action == "reject":
        for line in lines:
            line.review_status = ReviewStatus.REJECTED
            line.reviewed_at = datetime.utcnow()
            log_change("labor_line", line.id, "rejected")
        db.session.commit()
        return jsonify(updated=[_serialize(line) for line in lines], skipped=[])

    # approve: работу без нормы часов нельзя массово принять — она молча
    # уедет в итоговый документ с пустой нормой и нулевой суммой (см.
    # approve_labor_line выше). Остальные строки в пачке всё равно
    # принимаются — одна проблемная позиция не должна блокировать весь bulk.
    approvable = [line for line in lines if line.norm_hours is not None]
    skipped = [line for line in lines if line.norm_hours is None]
    for line in approvable:
        line.review_status = ReviewStatus.APPROVED
        line.reviewed_at = datetime.utcnow()
        log_change("labor_line", line.id, "approved")
    db.session.commit()

    return jsonify(
        updated=[_serialize(line) for line in approvable],
        skipped=[
            {"id": line.id, "description": line.description, "reason": "Не указана норма часов"}
            for line in skipped
        ],
    )
