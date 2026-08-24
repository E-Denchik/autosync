import os

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import (
    Contract,
    ContractFile,
    ContractHourlyRate,
    ContractLaborNorm,
    ContractPart,
    DocumentProcessingStatus,
)
from app.services.contract_catalog_import import ContractMergeError, merge_contracts
from app.services.document_parser import DocumentParseError
from app.services.history import log_change
from app.services.hourly_rate_import import import_hourly_rates
from app.services.job_queue import enqueue_import_contract
from app.services.pagination import paginate, paginated_response
from app.services.upload_helpers import compute_files_hash, display_filename, save_upload

bp = Blueprint("contracts", __name__)

RATE_TABLE_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv"}


def _contract_paths(contract: Contract) -> list[str]:
    return [contract.storage_path] + [f.storage_path for f in contract.extra_files]


def _serialize(contract: Contract) -> dict:
    return {
        "id": contract.id,
        "name": contract.name,
        "contragent_id": contract.contragent_id,
        "contragent_name": contract.contragent.name if contract.contragent else None,
        "original_filename": contract.original_filename,
        "status": contract.status.value,
        "error_message": contract.error_message,
        "active": contract.active,
        "parts_count": ContractPart.query.filter_by(contract_id=contract.id).count(),
        "labor_norms_count": ContractLaborNorm.query.filter_by(contract_id=contract.id).count(),
        "repair_orders_count": len(contract.repair_orders),
        "created_at": contract.created_at.isoformat(),
    }


@bp.get("")
def list_contracts():
    contracts = Contract.query.order_by(Contract.created_at.desc()).all()
    return jsonify([_serialize(c) for c in contracts])


@bp.get("/<int:contract_id>")
def get_contract(contract_id: int):
    contract = db.get_or_404(Contract, contract_id)
    return jsonify(_serialize(contract))


@bp.post("")
def create_contract():
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="Нужен хотя бы один файл 'file'"), 400

    name = (request.form.get("name") or "").strip() or display_filename(files[0].filename)
    contragent_id = request.form.get("contragent_id")
    vehicle_make = (request.form.get("vehicle_make") or "").strip() or None

    try:
        paths = [save_upload(f) for f in files]
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    # Тот же набор файлов уже когда-то загружали как каталог контракта —
    # переиспользуем существующий разобранный договор вместо создания
    # задвоенной копии (см. PROJECT.md: жалоба заказчика на дублирующиеся
    # договоры при повторной загрузке).
    content_hash = compute_files_hash(paths)
    existing = (
        Contract.query.filter_by(content_hash=content_hash, active=True, status=DocumentProcessingStatus.PARSED)
        .order_by(Contract.created_at.desc())
        .first()
    )
    if existing is not None:
        for path in paths:
            if os.path.isfile(path):
                os.remove(path)
        body = _serialize(existing)
        body["reused_existing_contract"] = True
        return jsonify(body), 200

    contract = Contract(
        name=name,
        contragent_id=int(contragent_id) if contragent_id else None,
        original_filename=display_filename(files[0].filename),
        storage_path=paths[0],
        content_hash=content_hash,
        status=DocumentProcessingStatus.UPLOADED,
    )
    db.session.add(contract)
    db.session.flush()
    for f, path in zip(files[1:], paths[1:]):
        db.session.add(
            ContractFile(contract_id=contract.id, original_filename=display_filename(f.filename), storage_path=path)
        )

    log_change("contract", contract.id, "created", details={"name": name})
    db.session.commit()

    enqueue_import_contract(contract.id, paths, vehicle_make)
    body = _serialize(contract)
    body["reused_existing_contract"] = False
    return jsonify(body), 202


@bp.post("/<int:contract_id>/import")
def import_more_files(contract_id: int):
    contract = db.get_or_404(Contract, contract_id)
    files = request.files.getlist("file")
    if not files:
        return jsonify(error="Нужен хотя бы один файл 'file'"), 400
    vehicle_make = (request.form.get("vehicle_make") or "").strip() or None

    try:
        paths = [save_upload(f) for f in files]
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    for f, path in zip(files, paths):
        db.session.add(
            ContractFile(contract_id=contract.id, original_filename=display_filename(f.filename), storage_path=path)
        )
    log_change("contract", contract.id, "import_added", details={"file_count": len(files)})
    db.session.commit()

    enqueue_import_contract(contract.id, paths, vehicle_make)
    return jsonify(_serialize(contract)), 202


@bp.get("/<int:contract_id>/status")
def contract_status(contract_id: int):
    contract = db.get_or_404(Contract, contract_id)
    return jsonify(id=contract.id, status=contract.status.value, error_message=contract.error_message)


@bp.get("/<int:contract_id>/parts")
def list_parts(contract_id: int):
    db.get_or_404(Contract, contract_id)
    query = ContractPart.query.filter_by(contract_id=contract_id).order_by(ContractPart.id)
    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(db.or_(ContractPart.article.ilike(f"%{q}%"), ContractPart.name.ilike(f"%{q}%")))
    items, total = paginate(query, request.args)
    return paginated_response(
        [
            {
                "id": p.id,
                "article": p.article,
                "name": p.name,
                "qty": float(p.qty) if p.qty is not None else None,
                "price": float(p.price) if p.price is not None else None,
            }
            for p in items
        ],
        total,
    )


@bp.get("/<int:contract_id>/labor-norms")
def list_labor_norms(contract_id: int):
    db.get_or_404(Contract, contract_id)
    query = ContractLaborNorm.query.filter_by(contract_id=contract_id).order_by(ContractLaborNorm.id)
    q = (request.args.get("q") or "").strip()
    if q:
        query = query.filter(ContractLaborNorm.operation_name.ilike(f"%{q}%"))
    items, total = paginate(query, request.args)
    return paginated_response(
        [
            {
                "id": n.id,
                "operation_name": n.operation_name,
                "vehicle_make": n.vehicle_make,
                "vehicle_model": n.vehicle_model,
                "norm_hours": float(n.norm_hours),
            }
            for n in items
        ],
        total,
    )


@bp.post("/<int:contract_id>/archive")
def archive_contract(contract_id: int):
    contract = db.get_or_404(Contract, contract_id)
    contract.active = False
    log_change("contract", contract.id, "archived")
    db.session.commit()
    return jsonify(_serialize(contract))


@bp.post("/<int:contract_id>/unarchive")
def unarchive_contract(contract_id: int):
    contract = db.get_or_404(Contract, contract_id)
    contract.active = True
    log_change("contract", contract.id, "unarchived")
    db.session.commit()
    return jsonify(_serialize(contract))


@bp.get("/<int:contract_id>/hourly-rates")
def list_hourly_rates(contract_id: int):
    db.get_or_404(Contract, contract_id)
    rates = ContractHourlyRate.query.filter_by(contract_id=contract_id).order_by(ContractHourlyRate.vehicle_make).all()
    return jsonify(
        [{"id": r.id, "vehicle_make": r.vehicle_make, "hourly_rate": float(r.hourly_rate)} for r in rates]
    )


@bp.post("/<int:contract_id>/hourly-rates")
def create_hourly_rate(contract_id: int):
    db.get_or_404(Contract, contract_id)
    body = request.get_json(force=True) or {}
    vehicle_make = (body.get("vehicle_make") or "").strip()
    if not vehicle_make:
        return jsonify(error="'vehicle_make' обязателен"), 400
    try:
        hourly_rate = float(body.get("hourly_rate"))
    except (TypeError, ValueError):
        return jsonify(error="'hourly_rate' должен быть числом"), 400
    if hourly_rate <= 0:
        return jsonify(error="'hourly_rate' должен быть положительным"), 400

    rate = ContractHourlyRate(contract_id=contract_id, vehicle_make=vehicle_make, hourly_rate=hourly_rate)
    db.session.add(rate)
    db.session.commit()
    return jsonify({"id": rate.id, "vehicle_make": rate.vehicle_make, "hourly_rate": float(rate.hourly_rate)}), 201


@bp.delete("/<int:contract_id>/hourly-rates/<int:rate_id>")
def delete_hourly_rate(contract_id: int, rate_id: int):
    rate = ContractHourlyRate.query.filter_by(id=rate_id, contract_id=contract_id).first_or_404()
    db.session.delete(rate)
    db.session.commit()
    return "", 204


@bp.post("/<int:contract_id>/hourly-rates/import")
def import_hourly_rates_file(contract_id: int):
    """Массовая загрузка ставок по маркам ТС файлом — см. тот же эндпоинт
    у контрагентов (app/api/contragents.py), формат файла не диктуется."""
    db.get_or_404(Contract, contract_id)
    file = request.files.get("file")
    if not file:
        return jsonify(error="Нужен файл 'file'"), 400

    try:
        path = save_upload(file, RATE_TABLE_EXTENSIONS)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    try:
        result = import_hourly_rates(ContractHourlyRate, "contract_id", contract_id, path)
    except DocumentParseError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        if os.path.isfile(path):
            os.remove(path)

    return jsonify(result), 200


@bp.delete("/<int:contract_id>")
def delete_contract(contract_id: int):
    contract = db.get_or_404(Contract, contract_id)
    if contract.repair_orders:
        return (
            jsonify(
                error=f"Договор используется в {len(contract.repair_orders)} заказ-наряде(ах) — "
                "удалить нельзя (историю заказ-нарядов нужно сохранить), но можно архивировать"
            ),
            409,
        )
    for path in _contract_paths(contract):
        if os.path.isfile(path):
            os.remove(path)
    log_change("contract", contract.id, "deleted")
    db.session.delete(contract)
    db.session.commit()
    return "", 204


@bp.post("/<int:source_id>/merge-into/<int:target_id>")
def merge_contract(source_id: int, target_id: int):
    """Уборка уже накопившихся дубликатов (см. create_contract — новые
    больше не плодятся): переносит заказ-наряды и уникальные позиции с
    source на target, затем удаляет опустевший source."""
    try:
        result = merge_contracts(source_id, target_id)
    except ContractMergeError as exc:
        return jsonify(error=str(exc)), 400
    target = db.get_or_404(Contract, target_id)
    return jsonify(contract=_serialize(target), **result)
