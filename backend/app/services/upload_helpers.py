from __future__ import annotations

import os
import uuid

from flask import current_app

from app.services.ocr import IMAGE_EXTENSIONS

ALLOWED_DOCUMENT_EXTENSIONS = {".xlsx", ".xlsm", ".xls", ".ods", ".csv", ".docx", ".pdf"} | IMAGE_EXTENSIONS


def display_filename(filename: str | None) -> str:
    return os.path.basename((filename or "").strip()) or "file"


def save_upload(file_storage, allowed_extensions: set[str] = ALLOWED_DOCUMENT_EXTENSIONS) -> str:
    ext = os.path.splitext(file_storage.filename or "")[1].lower()
    if ext not in allowed_extensions:
        raise ValueError(f"Неподдерживаемый тип файла: {ext}")

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, f"{uuid.uuid4().hex}{ext}")
    file_storage.save(path)
    return path
