import csv
import io
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from app.extensions import db
from app.models import DocumentTemplate, LaborLine, PartMatch, RepairOrder, RepairOrderStatus, ReviewStatus
from app.services.history import log_change

bp = Blueprint("repair_orders_matching", __name__)


def _serialize(match: PartMatch) -> dict:
    threshold = current_app.config["MATCH_CONFIDENCE_THRESHOLD"]
    return {
        "id": match.id,
        "repair_order_id": match.repair_order_id,
        "contract_article": match.contract_article,
        "contract_name": match.contract_name,
        "matched_article": match.matched_article,
        "matched_name": match.matched_name,
        "matched_price": float(match.matched_price) if match.matched_price is not None else None,
        # confidence_level различает exact / cross_ref / llm_guess — фронт
        # обязан отображать их визуально по-разному (см. ARCHITECTURE.md).
        "confidence_level": match.confidence_level.value,
        "confidence_score": match.confidence_score,
        "below_confidence_threshold": match.confidence_score is not None and match.confidence_score < threshold,
        "review_status": match.review_status.value,
        "manually_edited": match.manually_edited,
        # Обогащение из внутренней номенклатуры заказчика (см. NomenclatureEntry) —
        # nomenclature_source пуст, если в номенклатуре ничего не нашлось.
        "nomenclature_code": match.nomenclature_code,
        "nomenclature_cat_number": match.nomenclature_cat_number,
        "nomenclature_manufacturer": match.nomenclature_manufacturer,
        "nomenclature_unit": match.nomenclature_unit,
        "nomenclature_stock_qty": (
            float(match.nomenclature_stock_qty) if match.nomenclature_stock_qty is not None else None
        ),
        "nomenclature_reserved_qty": (
            float(match.nomenclature_reserved_qty) if match.nomenclature_reserved_qty is not None else None
        ),
        "nomenclature_in_production_qty": (
            float(match.nomenclature_in_production_qty)
            if match.nomenclature_in_production_qty is not None
            else None
        ),
        "nomenclature_ordered_qty": (
            float(match.nomenclature_ordered_qty) if match.nomenclature_ordered_qty is not None else None
        ),
        "nomenclature_warehouse": match.nomenclature_warehouse,
        "nomenclature_source": match.nomenclature_source,
    }


@bp.get("/<int:repair_order_id>")
def list_matches(repair_order_id: int):
    db.get_or_404(RepairOrder, repair_order_id)
    matches = (
        PartMatch.query.filter_by(repair_order_id=repair_order_id)
        .order_by(PartMatch.id)
        .all()
    )
    serialized = [_serialize(m) for m in matches]
    serialized.sort(
        key=lambda m: (
            m["review_status"] != "pending",
            not m["below_confidence_threshold"],
        )
    )
    return jsonify(serialized)


@bp.get("/<int:repair_order_id>/candidates")
def list_candidates(repair_order_id: int):
    """Позиции самого заказ-наряда — источник для ручного переподбора
    сопоставления на фронте (поиск по названию вместо слепого accept/reject)."""
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    return jsonify(repair_order.parsed_lines or [])


@bp.patch("/<int:match_id>")
def edit_match(match_id: int):
    """Ручная замена сопоставления оператором. confidence_level не трогаем —
    он описывает, как систему нашла соответствие; manually_edited фиксирует,
    что финальное решение принял человек. Сразу помечаем approved: раз
    оператор осознанно выбрал позицию, дальнейшего подтверждения не нужно.
    """
    match = db.get_or_404(PartMatch, match_id)
    body = request.get_json(force=True) or {}

    if "matched_article" not in body and "matched_name" not in body:
        return jsonify(error="Нужно указать хотя бы matched_article или matched_name"), 400

    match.matched_article = body.get("matched_article", match.matched_article)
    match.matched_name = body.get("matched_name", match.matched_name)
    if "matched_price" in body:
        match.matched_price = body.get("matched_price")
    match.manually_edited = True
    match.review_status = ReviewStatus.APPROVED
    match.reviewed_at = datetime.utcnow()

    log_change(
        "part_match",
        match.id,
        "edited",
        details={
            "matched_article": match.matched_article,
            "matched_name": match.matched_name,
            "matched_price": float(match.matched_price) if match.matched_price is not None else None,
        },
    )
    db.session.commit()
    return jsonify(_serialize(match))


@bp.post("/<int:match_id>/approve")
def approve_match(match_id: int):
    match = db.get_or_404(PartMatch, match_id)
    match.review_status = ReviewStatus.APPROVED
    match.reviewed_at = datetime.utcnow()
    log_change("part_match", match.id, "approved")
    db.session.commit()
    return jsonify(_serialize(match))


@bp.post("/<int:match_id>/reject")
def reject_match(match_id: int):
    match = db.get_or_404(PartMatch, match_id)
    match.review_status = ReviewStatus.REJECTED
    match.reviewed_at = datetime.utcnow()
    log_change("part_match", match.id, "rejected")
    db.session.commit()
    return jsonify(_serialize(match))


@bp.post("/bulk")
def bulk_review():
    """Массовое approve/reject нескольких позиций разом."""
    body = request.get_json(force=True) or {}
    ids = body.get("ids") or []
    action = body.get("action")

    if action not in ("approve", "reject"):
        return jsonify(error="'action' должен быть 'approve' или 'reject'"), 400
    if not ids:
        return jsonify(error="'ids' не может быть пустым"), 400

    status = ReviewStatus.APPROVED if action == "approve" else ReviewStatus.REJECTED
    matches = PartMatch.query.filter(PartMatch.id.in_(ids)).all()
    for match in matches:
        match.review_status = status
        match.reviewed_at = datetime.utcnow()
        log_change("part_match", match.id, status.value)
    db.session.commit()

    return jsonify([_serialize(m) for m in matches])


@bp.get("/<int:repair_order_id>/export")
def export_matches_csv(repair_order_id: int):
    """CSV-выгрузка всех сопоставлений (любого статуса) для аудита/архива —
    в отличие от generate-document, который отдаёт только approved-позиции
    в виде финального заказ-наряда."""
    db.get_or_404(RepairOrder, repair_order_id)
    matches = (
        PartMatch.query.filter_by(repair_order_id=repair_order_id).order_by(PartMatch.id).all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Артикул (договор)",
            "Наименование (договор)",
            "Сопоставлено с (артикул)",
            "Сопоставлено с (название)",
            "Цена",
            "Уверенность",
            "Статус проверки",
            "Ручная правка",
            "Код (номенклатура)",
            "№ кат.",
            "Производитель",
            "Ед.",
            "Остаток",
            "В резерве",
            "В производстве",
            "Заказано",
            "Склад",
        ]
    )
    for m in matches:
        writer.writerow(
            [
                m.contract_article or "",
                m.contract_name or "",
                m.matched_article or "",
                m.matched_name or "",
                m.matched_price if m.matched_price is not None else "",
                m.confidence_level.value,
                m.review_status.value,
                "да" if m.manually_edited else "нет",
                m.nomenclature_code or "",
                m.nomenclature_cat_number or "",
                m.nomenclature_manufacturer or "",
                m.nomenclature_unit or "",
                m.nomenclature_stock_qty if m.nomenclature_stock_qty is not None else "",
                m.nomenclature_reserved_qty if m.nomenclature_reserved_qty is not None else "",
                m.nomenclature_in_production_qty if m.nomenclature_in_production_qty is not None else "",
                m.nomenclature_ordered_qty if m.nomenclature_ordered_qty is not None else "",
                m.nomenclature_warehouse or "",
            ]
        )

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=repair_order_{repair_order_id}_matches.csv"},
    )


@bp.post("/<int:repair_order_id>/generate-document")
def generate_document(repair_order_id: int):
    """Генерирует итоговый заказ-наряд с подставленными ценами.

    Требует, чтобы все low-confidence позиции (llm_guess) были проверены
    человеком — иначе в документ могли бы попасть непроверенные догадки LLM.
    """
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    pending = PartMatch.query.filter_by(
        repair_order_id=repair_order_id, review_status=ReviewStatus.PENDING
    ).count()
    pending += LaborLine.query.filter_by(
        repair_order_id=repair_order_id, review_status=ReviewStatus.PENDING
    ).count()
    if pending:
        return jsonify(error=f"Есть {pending} непроверенных позиций, сгенерировать документ нельзя"), 409

    from app.services.document_generator import (
        generate_repair_order_document,
        generate_repair_order_document_from_template,
    )
    from app.services.document_template_engine import DocumentTemplateError

    template_id = request.args.get("template_id", type=int)
    unresolved_tokens = []
    if template_id:
        template = db.get_or_404(DocumentTemplate, template_id)
        try:
            output_path, unresolved_tokens = generate_repair_order_document_from_template(repair_order, template)
        except DocumentTemplateError as exc:
            return jsonify(error=str(exc)), 400
    else:
        output_path = generate_repair_order_document(repair_order)
    repair_order.generated_document_path = output_path
    repair_order.status = RepairOrderStatus.REVIEWED
    log_change("repair_order", repair_order.id, "reviewed")
    db.session.commit()

    response = send_file(output_path, as_attachment=True)
    if unresolved_tokens:
        response.headers["X-Unresolved-Tokens"] = ", ".join(unresolved_tokens)
    return response
