import os
import uuid

from flask import Blueprint, current_app, jsonify, request

from app.auth import login_required
from app.services.file_preview import FilePreviewError, TABLE_EXTENSIONS, preview_table

bp = Blueprint("file_preview", __name__)
bp.before_request(login_required(lambda: None))


@bp.post("")
def preview_uploaded_file():
    file_storage = request.files.get("file")
    if not file_storage or not file_storage.filename:
        return jsonify(error="Нужен файл 'file'"), 400
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in TABLE_EXTENSIONS:
        return jsonify(error=f"Предпросмотр не поддерживается для {ext}"), 400

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, f"preview-{uuid.uuid4().hex}{ext}")
    file_storage.save(temp_path)
    try:
        result = preview_table(temp_path)
    except FilePreviewError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        os.remove(temp_path)

    return jsonify(result)
