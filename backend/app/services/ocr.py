from __future__ import annotations

import logging
import os
from concurrent.futures import ProcessPoolExecutor

from PIL import Image

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
TESSERACT_LANG = "rus+eng"

# Не пропорционально ядрам без ограничения: рендер страницы в 300 DPI сам по
# себе заметно ест память, и после ~4 параллельных копий Tesseract на
# типичной машине заказчика дальнейший рост числа воркеров упирается в
# диск/память раньше, чем даёт выигрыш по времени.
_MAX_OCR_WORKERS = 4


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


def _ocr_pdf_page(args: tuple[str, int]) -> str:
    """Открывает PDF заново и распознаёт РОВНО одну страницу по индексу —
    выполняется в ОТДЕЛЬНОМ ПРОЦЕССЕ (см. extract_text_from_scanned_pdf),
    поэтому обязана быть простой module-level функцией (её нужно передать
    воркеру через pickle) и не может принять уже открытый объект
    pdfplumber.PDF — потокобезопасность параллельного рендеринга разных
    страниц ОДНОГО открытого документа в pdfplumber/pdfminer нигде не
    гарантирована, а раздельные процессы этот вопрос снимают полностью:
    каждый вызов сам открывает файл и не делит с другими вообще ничего."""
    import pdfplumber

    file_path, page_index = args
    with pdfplumber.open(file_path) as pdf:
        image = pdf.pages[page_index].to_image(resolution=300).original
    return _run_tesseract(image)


def _extract_text_from_scanned_pdf_sequential(file_path: str) -> str:
    import pdfplumber

    with pdfplumber.open(file_path) as pdf:
        texts = [_run_tesseract(page.to_image(resolution=300).original) for page in pdf.pages]
    return "\n\n".join(texts)


def extract_text_from_scanned_pdf(file_path: str) -> str:
    """Страницы скана — готовый, независимый друг от друга блок для
    параллельной обработки: Tesseract на страницу — отдельный вызов
    бинарника, а не Python-код под GIL, и честно масштабируется по ядрам —
    в отличие от локальной LLM (там несколько запросов делят ОДНУ и ту же
    уже загруженную модель, параллелить которую на CPU вредно, см.
    parallel.py). На многостраничном скане — разница в разы на типичной
    многоядерной машине.

    ProcessPoolExecutor, а не потоки (как в остальном проекте, см.
    parallel.py): процессы не делят между собой вообще ничего, поэтому
    вопрос потокобезопасности параллельного рендеринга снят полностью, а не
    просто "скорее всего сработает".

    Если пул процессов почему-то не смог отработать (тонкости спавна
    процессов из PyInstaller-сборки на конкретной машине — см. main() в
    native_app.py: multiprocessing.freeze_support() — либо любой другой
    сбой инфраструктуры) — тихо откатываемся на прежний последовательный
    путь вместо падения: параллелизм здесь — только оптимизация скорости,
    а не требование корректности результата."""
    import pdfplumber

    with pdfplumber.open(file_path) as pdf:
        page_count = len(pdf.pages)

    if page_count <= 1:
        return _extract_text_from_scanned_pdf_sequential(file_path)

    workers = min(_MAX_OCR_WORKERS, os.cpu_count() or 1, page_count)
    tasks = [(file_path, index) for index in range(page_count)]
    try:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            texts = list(executor.map(_ocr_pdf_page, tasks))
        return "\n\n".join(texts)
    except OcrError:
        # Не инфраструктурный сбой, а настоящая, детерминированная ошибка
        # распознавания (например, не установлен языковой пакет) — она
        # повторится один в один и в последовательном пути, откат её не
        # исправит, только удвоит работу впустую.
        raise
    except Exception:
        logger.warning(
            "Параллельный OCR по процессам не сработал для %s — распознаю "
            "страницы последовательно",
            file_path,
            exc_info=True,
        )
        return _extract_text_from_scanned_pdf_sequential(file_path)


def extract_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if is_image_extension(ext):
        return extract_text_from_image(file_path)
    if ext == ".pdf":
        return extract_text_from_scanned_pdf(file_path)
    raise OcrError(f"OCR не поддерживает формат {ext}")
