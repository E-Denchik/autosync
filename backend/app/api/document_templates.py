import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file

from app.extensions import db
from app.models import DocumentTemplate, RepairOrder
from app.services import document_generator, document_template_engine
from app.services.document_template_engine import DocumentTemplateError
from app.services.file_preview import FilePreviewError, preview_table
from app.services.history import log_change

bp = Blueprint("document_templates", __name__)

ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}


def _serialize(t: DocumentTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "original_filename": t.original_filename,
        "created_at": t.created_at.isoformat(),
    }


@bp.get("")
def list_templates():
    templates = DocumentTemplate.query.order_by(DocumentTemplate.name).all()
    return jsonify([_serialize(t) for t in templates])


@bp.get("/starter")
def download_starter():
    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    output_path = os.path.join(upload_dir, f"starter-template-{uuid.uuid4().hex}.xlsx")
    document_template_engine.build_starter_template(output_path)
    return send_file(output_path, as_attachment=True, download_name="autosync-starter-shablon.xlsx")


@bp.get("/<int:template_id>/file")
def download_template_file(template_id: int):
    template = db.get_or_404(DocumentTemplate, template_id)
    if not os.path.isfile(template.storage_path):
        return jsonify(error="Файл не найден на диске"), 404
    return send_file(template.storage_path, as_attachment=True, download_name=template.original_filename)


@bp.post("/preview-rendered")
def preview_rendered():
    repair_order = RepairOrder.query.order_by(RepairOrder.created_at.desc()).first()
    if repair_order is None:
        return jsonify(error="Нет ни одного заказ-наряда — нечем заполнить предпросмотр реальными данными"), 400

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)

    file_storage = request.files.get("file")
    cleanup_source_path = None
    if file_storage and file_storage.filename:
        ext = os.path.splitext(file_storage.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify(error=f"Неподдерживаемый формат {ext} — нужен .xlsx/.xlsm"), 400
        template_path = os.path.join(upload_dir, f"preview-src-{uuid.uuid4().hex}{ext}")
        file_storage.save(template_path)
        cleanup_source_path = template_path
    else:
        template_id = request.form.get("template_id")
        if not template_id:
            return jsonify(error="Нужен 'file' или 'template_id'"), 400
        template = db.get_or_404(DocumentTemplate, int(template_id))
        if not os.path.isfile(template.storage_path):
            return jsonify(error="Файл не найден на диске"), 404
        template_path = template.storage_path

    context, part_items, labor_items = document_generator.build_template_context(repair_order, approved_only=False)

    rendered_path = os.path.join(upload_dir, f"preview-rendered-{uuid.uuid4().hex}.xlsx")
    try:
        document_template_engine.render_template(template_path, rendered_path, context, part_items, labor_items)
    except DocumentTemplateError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        if cleanup_source_path:
            os.remove(cleanup_source_path)

    try:
        result = preview_table(rendered_path)
    except FilePreviewError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        os.remove(rendered_path)

    result["repair_order_id"] = repair_order.id
    return jsonify(result)


@bp.post("")
def upload_template():
    name = (request.form.get("name") or "").strip()
    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        return jsonify(error="Нужен файл 'file'"), 400
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify(error=f"Неподдерживаемый формат {ext} — нужен .xlsx/.xlsm"), 400
    if not name:
        name = os.path.splitext(file_storage.filename)[0]

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    stored_path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
    file_storage.save(stored_path)

    template = DocumentTemplate(
        name=name,
        original_filename=file_storage.filename,
        storage_path=stored_path,
    )
    db.session.add(template)
    db.session.flush()
    log_change("document_template", template.id, "created", details={"name": name})
    db.session.commit()
    return jsonify(_serialize(template)), 201


@bp.delete("/<int:template_id>")
def delete_template(template_id: int):
    template = db.get_or_404(DocumentTemplate, template_id)
    if os.path.isfile(template.storage_path):
        os.remove(template.storage_path)
    log_change("document_template", template.id, "deleted")
    db.session.delete(template)
    db.session.commit()
    return "", 204
