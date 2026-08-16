from __future__ import annotations

import os

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
TESSERACT_LANG = "rus+eng"


class OcrError(RuntimeError):
    pass


def is_image_extension(ext: str) -> bool:
    return ext.lower() in IMAGE_EXTENSIONS


def _run_tesseract(image: Image.Image) -> str:
    import pytesseract

    try:
        return pytesseract.image_to_string(image, lang=TESSERACT_LANG)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrError("Tesseract OCR не установлен на этой машине") from exc
    except pytesseract.TesseractError as exc:
        if "Failed loading language" in str(exc):
            raise OcrError(
                "На этой машине не установлен языковой пакет Tesseract для русского "
                "(пакет tesseract-ocr-rus)"
            ) from exc
        raise OcrError(f"Ошибка распознавания текста: {exc}") from exc


def extract_text_from_image(file_path: str) -> str:
    try:
        image = Image.open(file_path)
    except Exception as exc:
        raise OcrError(f"Не удалось открыть изображение: {exc}") from exc
    return _run_tesseract(image)


def extract_text_from_scanned_pdf(file_path: str) -> str:
    import pdfplumber

    texts = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            texts.append(_run_tesseract(page.to_image(resolution=300).original))
    return "\n\n".join(texts)


def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if is_image_extension(ext):
        return extract_text_from_image(file_path)
    if ext == ".pdf":
        return extract_text_from_scanned_pdf(file_path)
    raise OcrError(f"OCR не поддерживает формат {ext}")
