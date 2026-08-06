from datetime import datetime

from flask import Blueprint, jsonify, send_file

from app.extensions import db
from app.models import PartMatch, RepairOrder, ReviewStatus

bp = Blueprint("repair_orders_matching", __name__)


def _serialize(match: PartMatch) -> dict:
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
        "review_status": match.review_status.value,
    }


@bp.get("/<int:repair_order_id>")
def list_matches(repair_order_id: int):
    db.get_or_404(RepairOrder, repair_order_id)
    matches = (
        PartMatch.query.filter_by(repair_order_id=repair_order_id)
        .order_by(PartMatch.id)
        .all()
    )
    return jsonify([_serialize(m) for m in matches])


@bp.post("/<int:match_id>/approve")
def approve_match(match_id: int):
    match = db.get_or_404(PartMatch, match_id)
    match.review_status = ReviewStatus.APPROVED
    match.reviewed_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_serialize(match))


@bp.post("/<int:match_id>/reject")
def reject_match(match_id: int):
    match = db.get_or_404(PartMatch, match_id)
    match.review_status = ReviewStatus.REJECTED
    match.reviewed_at = datetime.utcnow()
    db.session.commit()
    return jsonify(_serialize(match))


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
    if pending:
        return jsonify(error=f"Есть {pending} непроверенных позиций, сгенерировать документ нельзя"), 409

    from app.services.document_generator import generate_repair_order_document

    output_path = generate_repair_order_document(repair_order)
    repair_order.generated_document_path = output_path
    db.session.commit()

    return send_file(output_path, as_attachment=True)
