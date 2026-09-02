from __future__ import annotations

import hashlib
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


def save_uploads(file_storages, allowed_extensions: set[str] = ALLOWED_DOCUMENT_EXTENSIONS) -> list[str]:
    paths: list[str] = []
    try:
        for file_storage in file_storages:
            paths.append(save_upload(file_storage, allowed_extensions))
    except (OSError, ValueError):
        for path in paths:
            if os.path.isfile(path):
                os.remove(path)
        raise
    return paths


def compute_files_hash(paths: list[str]) -> str:
    """Хэш содержимого набора файлов — определяет "тот же самый файл(ы)
    загрузили ещё раз" независимо от нового случайного имени на диске
    (см. save_upload) или порядка байт: каждый файл хэшируется отдельно,
    итоговые хэши сортируются (порядок выбора файлов в форме не должен
    менять результат) и хэшируются вместе с их количеством."""
    def _hash_file(path: str) -> str:
        with open(path, "rb") as f:
            digest = hashlib.sha256()
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
            return digest.hexdigest()

    per_file = sorted(_hash_file(p) for p in paths)
    combined = hashlib.sha256()
    combined.update(str(len(paths)).encode())
    for digest in per_file:
        combined.update(digest.encode())
    return combined.hexdigest()
