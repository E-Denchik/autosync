import os

from flask import Blueprint, current_app, jsonify, request, send_file

from app.extensions import db
from app.models import (
    Contract,
    ContractFile,
    DocumentProcessingStatus,
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderFile,
    RepairOrderStatus,
    ReviewStatus,
)
from app.services.history import log_change
from app.services.job_queue import enqueue_process_upload
from app.services.pagination import paginate, paginated_response
from app.services import progress_tracker
from app.services.upload_helpers import compute_files_hash, display_filename, save_upload as _save_upload

bp = Blueprint("repair_orders_upload", __name__)


@bp.post("")
def upload_documents():
    """Принимает заказ-наряд (один или несколько файлов, например отдельные
    страницы) и либо новый договор файлом, либо ссылку на уже загруженный
    ранее каталог контракта (contract_id) — см. app/api/contracts.py."""
    order_files = request.files.getlist("repair_order")
    if not order_files:
        return jsonify(error="Нужен файл repair_order"), 400

    existing_contract_id = request.form.get("contract_id")
    contract_files = request.files.getlist("contract")
    if not existing_contract_id and not contract_files:
        return jsonify(error="Нужен либо файл contract, либо contract_id уже загруженного договора"), 400

    try:
        order_paths = [_save_upload(f) for f in order_files]
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    reused_existing_contract = False
    if existing_contract_id:
        contract = db.session.get(Contract, int(existing_contract_id))
        if not contract:
            return jsonify(error="Указанный договор не найден"), 404
        if contract.status != DocumentProcessingStatus.PARSED:
            return jsonify(error="Указанный договор ещё не разобран — подождите и попробуйте снова"), 409
    else:
        try:
            contract_paths = [_save_upload(f) for f in contract_files]
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        # Тот же набор файлов уже когда-то загружали ("Новый файл" выбран по
        # привычке вместо "Уже загруженный контракт") — переиспользуем
        # существующий разобранный договор вместо создания задвоенной копии
        # (см. PROJECT.md: жалоба заказчика на дублирующиеся договоры).
        content_hash = compute_files_hash(contract_paths)
        contract = (
            Contract.query.filter_by(content_hash=content_hash, active=True, status=DocumentProcessingStatus.PARSED)
            .order_by(Contract.created_at.desc())
            .first()
        )
        if contract is not None:
            reused_existing_contract = True
            for path in contract_paths:
                if os.path.isfile(path):
                    os.remove(path)
        else:
            contract = Contract(
                original_filename=display_filename(contract_files[0].filename),
                storage_path=contract_paths[0],
                content_hash=content_hash,
                status=DocumentProcessingStatus.UPLOADED,
            )
            db.session.add(contract)
            db.session.flush()
            for f, path in zip(contract_files[1:], contract_paths[1:]):
                db.session.add(
                    ContractFile(
                        contract_id=contract.id, original_filename=display_filename(f.filename), storage_path=path
                    )
                )

    contragent_id = request.form.get("contragent_id")
    repair_order = RepairOrder(
        contract_id=contract.id,
        contragent_id=int(contragent_id) if contragent_id else None,
        vehicle_make=(request.form.get("vehicle_make") or "").strip() or None,
        vehicle_model=(request.form.get("vehicle_model") or "").strip() or None,
        vehicle_year=int(request.form["vehicle_year"]) if request.form.get("vehicle_year") else None,
        vehicle_vin=(request.form.get("vehicle_vin") or "").strip() or None,
        original_filename=display_filename(order_files[0].filename),
        storage_path=order_paths[0],
        status=RepairOrderStatus.UPLOADED,
    )
    db.session.add(repair_order)
    db.session.flush()
    for f, path in zip(order_files[1:], order_paths[1:]):
        db.session.add(
            RepairOrderFile(
                repair_order_id=repair_order.id, original_filename=display_filename(f.filename), storage_path=path
            )
        )

    log_change(
        "repair_order",
        repair_order.id,
        "created",
        details={
            "original_filename": repair_order.original_filename,
            "contract_filename": contract.original_filename,
            "order_file_count": len(order_files),
            "contract_file_count": len(contract_files),
            "reused_existing_contract": reused_existing_contract,
        },
    )
    db.session.commit()

    enqueue_process_upload(contract.id, repair_order.id)

    return (
        jsonify(
            contract_id=contract.id,
            repair_order_id=repair_order.id,
            reused_existing_contract=reused_existing_contract,
            reused_contract_name=contract.name or contract.original_filename if reused_existing_contract else None,
        ),
        202,
    )


@bp.get("")
def list_repair_orders():
    """История загруженных заказ-нарядов для страницы со списком на фронте."""
    query = RepairOrder.query.order_by(RepairOrder.created_at.desc())
    orders, total_count = paginate(query, request.args)
    result = []
    for order in orders:
        total = PartMatch.query.filter_by(repair_order_id=order.id).count()
        pending = PartMatch.query.filter_by(
            repair_order_id=order.id, review_status=ReviewStatus.PENDING
        ).count()
        labor_total = LaborLine.query.filter_by(repair_order_id=order.id).count()
        labor_pending = LaborLine.query.filter_by(
            repair_order_id=order.id, review_status=ReviewStatus.PENDING
        ).count()
        result.append(
            {
                "id": order.id,
                "order_number": order.order_number,
                "order_date": order.order_date,
                "original_filename": order.original_filename,
                "extra_file_count": len(order.extra_files),
                "contract_filename": order.contract.original_filename if order.contract else None,
                "status": order.status.value,
                "matches_total": total,
                "matches_pending": pending,
                "labor_total": labor_total,
                "labor_pending": labor_pending,
                "vehicle_make": order.vehicle_make,
                "vehicle_model": order.vehicle_model,
                "contragent_name": order.contragent.name if order.contragent else None,
                "created_at": order.created_at.isoformat(),
            }
        )
    return paginated_response(result, total_count)


@bp.patch("/<int:repair_order_id>")
def update_repair_order(repair_order_id: int):
    """Правка метаданных уже загруженного заказ-наряда (контрагент/машина).

    Уже сопоставленные строки работ/запчастей не пересчитываются — как и
    везде в этом модуле, конкретную строку правят вручную через PATCH
    .../labor/<id> или .../matching/<id>, если смена контрагента должна
    повлиять на цену."""
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    body = request.get_json(force=True) or {}

    if "contragent_id" in body:
        contragent_id = body.get("contragent_id")
        repair_order.contragent_id = int(contragent_id) if contragent_id else None
    if "vehicle_make" in body:
        repair_order.vehicle_make = (body.get("vehicle_make") or "").strip() or None
    if "vehicle_model" in body:
        repair_order.vehicle_model = (body.get("vehicle_model") or "").strip() or None
    if "vehicle_year" in body:
        vehicle_year = body.get("vehicle_year")
        try:
            repair_order.vehicle_year = int(vehicle_year) if vehicle_year not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify(error="'vehicle_year' должен быть числом"), 400
    if "vehicle_vin" in body:
        repair_order.vehicle_vin = (body.get("vehicle_vin") or "").strip() or None
    if "order_number" in body:
        repair_order.order_number = (body.get("order_number") or "").strip() or None
    if "order_date" in body:
        repair_order.order_date = (body.get("order_date") or "").strip() or None

    log_change(
        "repair_order",
        repair_order.id,
        "edited",
        details={
            "contragent_id": repair_order.contragent_id,
            "vehicle_make": repair_order.vehicle_make,
            "vehicle_model": repair_order.vehicle_model,
            "vehicle_year": repair_order.vehicle_year,
            "vehicle_vin": repair_order.vehicle_vin,
            "order_number": repair_order.order_number,
            "order_date": repair_order.order_date,
        },
    )
    db.session.commit()
    return jsonify(
        id=repair_order.id,
        contragent_id=repair_order.contragent_id,
        contragent_name=repair_order.contragent.name if repair_order.contragent else None,
        vehicle_make=repair_order.vehicle_make,
        vehicle_model=repair_order.vehicle_model,
        vehicle_year=repair_order.vehicle_year,
        vehicle_vin=repair_order.vehicle_vin,
        order_number=repair_order.order_number,
        order_date=repair_order.order_date,
    )


@bp.delete("/<int:repair_order_id>")
def delete_repair_order(repair_order_id: int):
    """Удаляет заказ-наряд целиком — вместе с сопоставленными позициями,
    работами и загруженными файлами. В отличие от договора (см.
    contracts.py: delete_contract), тут нет причины блокировать удаление
    по статусу — заказ-наряд не переиспользуется другими записями, и
    заказчик явно должен иметь возможность убрать ошибочную/тестовую
    загрузку в любом состоянии."""
    repair_order = db.get_or_404(RepairOrder, repair_order_id)

    paths = [repair_order.storage_path] + [f.storage_path for f in repair_order.extra_files]
    if repair_order.generated_document_path:
        paths.append(repair_order.generated_document_path)
    for path in paths:
        if path and os.path.isfile(path):
            os.remove(path)

    log_change(
        "repair_order", repair_order.id, "deleted", details={"original_filename": repair_order.original_filename}
    )
    db.session.delete(repair_order)
    db.session.commit()
    return "", 204


@bp.get("/<int:repair_order_id>/status")
def upload_status(repair_order_id: int):
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    return jsonify(
        id=repair_order.id,
        status=repair_order.status.value,
        error_message=repair_order.error_message,
        # Видно сразу на странице проверки, что контрагент/машина реально
        # привязались к заказ-наряду — без этого не было способа убедиться,
        # что выбор на странице загрузки к чему-то привёл.
        contragent_name=repair_order.contragent.name if repair_order.contragent else None,
        vehicle_make=repair_order.vehicle_make,
        vehicle_model=repair_order.vehicle_model,
        order_number=repair_order.order_number,
        order_date=repair_order.order_date,
        review_summary=repair_order.review_summary,
        # Пока идёт парсинг/сопоставление — фронт считает от этой отметки,
        # сколько времени уже идёт обработка (см. ReviewMatches.jsx), чтобы
        # не выглядело зависшим на долгих файлах.
        created_at=repair_order.created_at.isoformat(),
        # {"current": N, "total": M} — сколько кусков текста/позиций уже
        # обработано из скольки в АКТИВНОЙ прямо сейчас фазе (см.
        # services/progress_tracker.py); null, если фаза ещё не начала
        # отчитываться (только что стартовала) или прогресс для нужного шага
        # не отслеживается (например, быстрый жёсткий парсер без LLM).
        # Фронт считает по этим числам ожидаемое оставшееся время.
        progress=progress_tracker.get(repair_order.id),
    )


@bp.get("/<int:repair_order_id>/file")
def download_source_file(repair_order_id: int):
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    source = request.args.get("source", "order")
    if source == "contract":
        path, name = repair_order.contract.storage_path, repair_order.contract.original_filename
    elif source == "order":
        path, name = repair_order.storage_path, repair_order.original_filename
    else:
        return jsonify(error="source должен быть 'order' или 'contract'"), 400
    if not os.path.isfile(path):
        return jsonify(error="Файл не найден на диске"), 404
    return send_file(path, as_attachment=True, download_name=name)
