import os
import uuid

from flask import Blueprint, current_app, jsonify, request

from app.auth import get_current_user, login_required
from app.extensions import db
from app.models import (
    Contract,
    DocumentProcessingStatus,
    LaborLine,
    PartMatch,
    RepairOrder,
    RepairOrderStatus,
    ReviewStatus,
)
from app.services.history import log_change
from app.services.job_queue import enqueue_process_upload
from app.services.pagination import paginate, paginated_response

bp = Blueprint("repair_orders_upload", __name__)
bp.before_request(login_required(lambda: None))

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"}


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
    """Принимает договор + заказ-наряд, ставит задачу парсинга/сопоставления в очередь."""
    if "contract" not in request.files or "repair_order" not in request.files:
        return jsonify(error="Нужны оба файла: contract и repair_order"), 400

    contract_file = request.files["contract"]
    order_file = request.files["repair_order"]

    try:
        contract_path = _save_upload(contract_file)
        order_path = _save_upload(order_file)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    contract = Contract(
        original_filename=display_filename(contract_file.filename),
        storage_path=contract_path,
        status=DocumentProcessingStatus.UPLOADED,
    )
    db.session.add(contract)
    db.session.flush()

    contragent_id = request.form.get("contragent_id")
    repair_order = RepairOrder(
        contract_id=contract.id,
        contragent_id=int(contragent_id) if contragent_id else None,
        vehicle_make=(request.form.get("vehicle_make") or "").strip() or None,
        vehicle_model=(request.form.get("vehicle_model") or "").strip() or None,
        vehicle_year=int(request.form["vehicle_year"]) if request.form.get("vehicle_year") else None,
        vehicle_vin=(request.form.get("vehicle_vin") or "").strip() or None,
        original_filename=display_filename(order_file.filename),
        storage_path=order_path,
        status=RepairOrderStatus.UPLOADED,
    )
    db.session.add(repair_order)
    db.session.flush()

    log_change(
        "repair_order",
        repair_order.id,
        "created",
        actor=get_current_user(),
        details={
            "original_filename": repair_order.original_filename,
            "contract_filename": contract.original_filename,
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
