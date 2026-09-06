import csv
import io
from datetime import datetime

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from app.extensions import db
from app.models import (
    ConfidenceLevel,
    ContractPart,
    DocumentTemplate,
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)
from app.services.confidence_display import is_verified
from app.services.history import log_change

bp = Blueprint("repair_orders_matching", __name__)

CONTRACT_CANDIDATE_SEARCH_LIMIT = 30


def _match_category(match: PartMatch) -> str:
    """Единая, машиночитаемая категория того, КАК позиция была сопоставлена —
    для статистики на странице проверки (см. ReviewMatches.jsx), чтобы не
    пересчитывать её на фронте из нескольких разрозненных полей (и не
    рассинхронизировать логику классификации между бэком и фронтом)."""
    if match.confidence_level == ConfidenceLevel.EXACT:
        return "exact"
    if match.confidence_level == ConfidenceLevel.CROSS_REF:
        return "cross_ref"
    if match.raw_match_data and match.raw_match_data.get("source") == "llm_error":
        return "llm_error"
    if match.matched_name is None:
        return "no_match"
    return "llm_guess"


def _serialize(match: PartMatch) -> dict:
    threshold = current_app.config["MATCH_CONFIDENCE_THRESHOLD"]
    category = _match_category(match)
    return {
        "id": match.id,
        "repair_order_id": match.repair_order_id,
        "contract_article": match.contract_article,
        "contract_name": match.contract_name,
        "contract_qty": float(match.contract_qty) if match.contract_qty is not None else None,
        "matched_article": match.matched_article,
        "matched_name": match.matched_name,
        "matched_price": float(match.matched_price) if match.matched_price is not None else None,
        # confidence_level различает exact / cross_ref / llm_guess — фронт
        # обязан отображать их визуально по-разному (см. ARCHITECTURE.md).
        "confidence_level": match.confidence_level.value,
        "confidence_score": match.confidence_score,
        "below_confidence_threshold": match.confidence_score is not None and match.confidence_score < threshold,
        # Свёрнутый статус для оператора: "проверено" или "догадка" — см.
        # confidence_display.is_verified. Не путать с review_status:
        # is_verified описывает, насколько само сопоставление выглядит
        # надёжным, а review_status — принял ли его кто-то из людей.
        "is_verified": is_verified(
            match_category=category,
            confidence_score=match.confidence_score,
            review_status=match.review_status.value,
            manually_edited=match.manually_edited,
            threshold=threshold,
            has_value=match.matched_name is not None,
        ),
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
        # Позиция ушла на ручную проверку не потому, что ИИ честно не нашла
        # совпадение, а потому, что llm-service вообще не ответил (сервис не
        # запущен, модель не выбрана и т.п., см. matcher.py) — раньше это
        # выглядело для проверяющего ТОЧНО так же, как обычное "не найдено",
        # хотя причина и решение (перезапустить/настроить LLM и загрузить
        # заново) совсем другие.
        "llm_error": (
            match.raw_match_data.get("error")
            if match.raw_match_data and match.raw_match_data.get("source") == "llm_error"
            else None
        ),
        "match_category": category,
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
    """Позиции КАТАЛОГА ДОГОВОРА (не самого заказ-наряда!) — источник для
    ручного переподбора сопоставления на фронте. Раньше тут отдавались
    parsed_lines самого заказ-наряда — то есть оператор при ручной правке
    искал среди тех же черновых строк, которые как раз и нужно было
    сопоставить с договором, а не среди реального прайса с проверенными
    артикулами/ценами (см. жалобу заказчика — в поиске всплывали позиции
    заказ-наряда с их собственными "как есть" ценами, не из договора).
    Договор может быть большим (50 000+ позиций, см. PROJECT.md), поэтому
    поиск идёт на бэкенде по 'q' с лимитом, а не отдаётся целиком."""
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    q = (request.args.get("q") or "").strip()
    query = ContractPart.query.filter_by(contract_id=repair_order.contract_id)
    if q:
        query = query.filter(db.or_(ContractPart.name.ilike(f"%{q}%"), ContractPart.article.ilike(f"%{q}%")))
    parts = query.order_by(ContractPart.name).limit(CONTRACT_CANDIDATE_SEARCH_LIMIT).all()
    return jsonify(
        [
            {
                "article": p.article,
                "name": p.name,
                "price": float(p.price) if p.price is not None else None,
            }
            for p in parts
        ]
    )


@bp.post("/<int:repair_order_id>/parts")
def add_part(repair_order_id: int):
    """Добавляет НОВУЮ позицию в заказ-наряд вручную — например, найденную
    оператором через поиск по поставщикам (Rossco/АвтоЕвро/Москворечье,
    см. app/api/parts_suppliers.py), которой не было в исходном файле.
    Сразу approved: раз оператор осознанно выбрал позицию, дальнейшего
    подтверждения не нужно (тот же принцип, что и в edit_match)."""
    db.get_or_404(RepairOrder, repair_order_id)
    body = request.get_json(force=True) or {}

    matched_name = (body.get("matched_name") or "").strip()
    if not matched_name:
        return jsonify(error="'matched_name' обязателен"), 400

    match = PartMatch(
        repair_order_id=repair_order_id,
        contract_article=body.get("matched_article"),
        contract_name=matched_name,
        contract_qty=body.get("contract_qty"),
        matched_article=body.get("matched_article"),
        matched_name=matched_name,
        matched_price=body.get("matched_price"),
        confidence_level=ConfidenceLevel.EXACT,
        confidence_score=1.0,
        review_status=ReviewStatus.APPROVED,
        manually_edited=True,
        reviewed_at=datetime.utcnow(),
        raw_match_data={"source": body.get("source") or "manual_add"},
    )
    db.session.add(match)
    db.session.flush()
    log_change(
        "part_match",
        match.id,
        "created",
        details={"matched_article": match.matched_article, "matched_name": match.matched_name, "source": "manual_add"},
    )
    db.session.commit()
    return jsonify(_serialize(match)), 201


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
    if "contract_qty" in body:
        match.contract_qty = body.get("contract_qty")
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
