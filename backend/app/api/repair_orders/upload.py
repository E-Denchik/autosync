import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file

from app.auth import get_current_user, login_required
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
from app.services.ocr import IMAGE_EXTENSIONS
from app.services.pagination import paginate, paginated_response

bp = Blueprint("repair_orders_upload", __name__)
bp.before_request(login_required(lambda: None))

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"} | IMAGE_EXTENSIONS


def display_filename(filename: str | None) -> str:
    return os.path.basename((filename or "").strip()) or "file"


def _save_upload(file_storage) -> str:
    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Неподдерживаемый тип файла: {ext}")

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(upload_dir, stored_name)
    file_storage.save(path)
    return path


@bp.post("")
def upload_documents():
    """Принимает договор + заказ-наряд (каждый — один или несколько файлов,
    например отдельные страницы), ставит задачу парсинга/сопоставления в очередь."""
    contract_files = request.files.getlist("contract")
    order_files = request.files.getlist("repair_order")
    if not contract_files or not order_files:
        return jsonify(error="Нужны оба файла: contract и repair_order"), 400

    try:
        contract_paths = [_save_upload(f) for f in contract_files]
        order_paths = [_save_upload(f) for f in order_files]
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    contract = Contract(
        original_filename=display_filename(contract_files[0].filename),
        storage_path=contract_paths[0],
        status=DocumentProcessingStatus.UPLOADED,
    )
    db.session.add(contract)
    db.session.flush()
    for f, path in zip(contract_files[1:], contract_paths[1:]):
        db.session.add(
            ContractFile(contract_id=contract.id, original_filename=display_filename(f.filename), storage_path=path)
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
        actor=get_current_user(),
        details={
            "original_filename": repair_order.original_filename,
            "contract_filename": contract.original_filename,
            "order_file_count": len(order_files),
            "contract_file_count": len(contract_files),
        },
    )
    db.session.commit()

    enqueue_process_upload(contract.id, repair_order.id)

    return jsonify(contract_id=contract.id, repair_order_id=repair_order.id), 202


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


@bp.get("/<int:repair_order_id>/status")
def upload_status(repair_order_id: int):
    repair_order = db.get_or_404(RepairOrder, repair_order_id)
    return jsonify(
        id=repair_order.id,
        status=repair_order.status.value,
        error_message=repair_order.error_message,
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
