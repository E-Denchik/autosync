import pytest
from PIL import Image

from app.services.ocr import (
    OcrError,
    extract_text,
    extract_text_from_image,
    is_image_extension,
)


def test_is_image_extension():
    for ext in (".jpg", ".JPG", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        assert is_image_extension(ext) is True
    for ext in (".pdf", ".xlsx", ".txt", ""):
        assert is_image_extension(ext) is False


def test_extract_text_from_image_raises_ocr_error_on_broken_file(tmp_path):
    bad_file = tmp_path / "not-an-image.jpg"
    bad_file.write_bytes(b"this is definitely not a jpeg")

    with pytest.raises(OcrError, match="Не удалось открыть изображение"):
        extract_text_from_image(str(bad_file))


def test_extract_text_from_image_raises_ocr_error_on_missing_file():
    with pytest.raises(OcrError, match="Не удалось открыть изображение"):
        extract_text_from_image("/nonexistent/path/to/file.jpg")


def test_extract_text_maps_tesseract_not_found(tmp_path, monkeypatch):
    """Регрессия-хартия: на машине без установленного Tesseract пользователь
    должен увидеть понятную русскую ошибку, а не голый EnvironmentError."""
    import pytesseract

    img_path = tmp_path / "scan.png"
    Image.new("RGB", (10, 10)).save(img_path)

    def fake_image_to_string(image, lang=None):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr("pytesseract.image_to_string", fake_image_to_string)

    with pytest.raises(OcrError, match="не установлен на этой машине"):
        extract_text(str(img_path))


def test_extract_text_maps_missing_russian_language_pack(tmp_path, monkeypatch):
    import pytesseract

    img_path = tmp_path / "scan.png"
    Image.new("RGB", (10, 10)).save(img_path)

    def fake_image_to_string(image, lang=None):
        raise pytesseract.TesseractError(1, "Failed loading language 'rus'")

    monkeypatch.setattr("pytesseract.image_to_string", fake_image_to_string)

    with pytest.raises(OcrError, match="tesseract-ocr-rus"):
        extract_text(str(img_path))


def test_extract_text_maps_other_tesseract_errors_generically(tmp_path, monkeypatch):
    import pytesseract

    img_path = tmp_path / "scan.png"
    Image.new("RGB", (10, 10)).save(img_path)

    def fake_image_to_string(image, lang=None):
        raise pytesseract.TesseractError(1, "some other failure")

    monkeypatch.setattr("pytesseract.image_to_string", fake_image_to_string)

    with pytest.raises(OcrError, match="Ошибка распознавания текста"):
        extract_text(str(img_path))


def test_extract_text_returns_recognized_text(tmp_path, monkeypatch):
    img_path = tmp_path / "scan.png"
    Image.new("RGB", (10, 10)).save(img_path)

    monkeypatch.setattr("pytesseract.image_to_string", lambda image, lang=None: "распознанный текст")

    assert extract_text(str(img_path)) == "распознанный текст"


def test_extract_text_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "file.docx"
    path.write_bytes(b"x")

    with pytest.raises(OcrError, match="не поддерживает формат"):
        extract_text(str(path))


class _FakePage:
    def __init__(self, index):
        self._index = index

    def to_image(self, resolution=300):
        return self

    @property
    def original(self):
        return f"page-{self._index}"


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeExecutor:
    """Тот же интерфейс, что и ProcessPoolExecutor (context manager + map),
    но выполняет задачи прямо в текущем процессе — проверяет СКЛЕИВАЮЩИЙ
    код (map_with...) без реального спавна процессов/Tesseract/PDF."""

    def __init__(self, max_workers=None):
        self.max_workers = max_workers

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def map(self, fn, tasks):
        return [fn(t) for t in tasks]


def test_extract_text_from_scanned_pdf_single_page_skips_process_pool(tmp_path, monkeypatch):
    """Одна страница — распознаём прямо в текущем процессе, не тратим время
    на спавн ProcessPoolExecutor там, где параллелить нечего."""
    import app.services.ocr as ocr_module

    fake_pdf = _FakePdf([_FakePage(0)])
    monkeypatch.setattr("pdfplumber.open", lambda path: fake_pdf)
    monkeypatch.setattr(ocr_module, "_run_tesseract", lambda image: f"text:{image}")

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("ProcessPoolExecutor не должен вызываться для одной страницы")

    monkeypatch.setattr(ocr_module, "ProcessPoolExecutor", _must_not_be_called)

    result = ocr_module.extract_text_from_scanned_pdf(str(tmp_path / "scan.pdf"))
    assert result == "text:page-0"


def test_extract_text_from_scanned_pdf_joins_pages_in_order(tmp_path, monkeypatch):
    """Многостраничный скан идёт через пул (см. _FakeExecutor) — результат
    должен склеиться в исходном порядке страниц, а не в порядке завершения."""
    import app.services.ocr as ocr_module

    fake_pdf = _FakePdf([_FakePage(0), _FakePage(1), _FakePage(2)])
    monkeypatch.setattr("pdfplumber.open", lambda path: fake_pdf)
    monkeypatch.setattr(ocr_module, "_run_tesseract", lambda image: f"text:{image}")
    monkeypatch.setattr(ocr_module, "ProcessPoolExecutor", _FakeExecutor)

    result = ocr_module.extract_text_from_scanned_pdf(str(tmp_path / "scan.pdf"))
    assert result == "text:page-0\n\ntext:page-1\n\ntext:page-2"


def test_extract_text_from_scanned_pdf_falls_back_to_sequential_when_pool_breaks(tmp_path, monkeypatch):
    """Регрессия: если ProcessPoolExecutor почему-то не смог отработать
    (например, тонкости спавна процессов на конкретной PyInstaller-сборке —
    см. docstring extract_text_from_scanned_pdf) — не роняем распознавание
    целиком, а тихо возвращаемся к последовательному пути, который работал
    и раньше."""
    import app.services.ocr as ocr_module

    fake_pdf = _FakePdf([_FakePage(0), _FakePage(1), _FakePage(2)])
    monkeypatch.setattr("pdfplumber.open", lambda path: fake_pdf)
    monkeypatch.setattr(ocr_module, "_run_tesseract", lambda image: f"text:{image}")

    def _broken_pool(*args, **kwargs):
        raise RuntimeError("simulated process pool failure")

    monkeypatch.setattr(ocr_module, "ProcessPoolExecutor", _broken_pool)

    result = ocr_module.extract_text_from_scanned_pdf(str(tmp_path / "scan.pdf"))
    assert result == "text:page-0\n\ntext:page-1\n\ntext:page-2"


def test_extract_text_from_scanned_pdf_does_not_swallow_real_ocr_error(tmp_path, monkeypatch):
    """В отличие от инфраструктурного сбоя пула, настоящая ошибка
    распознавания (например, не установлен языковой пакет) детерминирована
    и повторится в последовательном пути один в один — откат её не
    исправит, поэтому она должна пробрасываться сразу, а не тонуть в
    молчаливом фолбэке."""
    import app.services.ocr as ocr_module

    fake_pdf = _FakePdf([_FakePage(0), _FakePage(1)])
    monkeypatch.setattr("pdfplumber.open", lambda path: fake_pdf)

    def _raise_ocr_error(image):
        raise OcrError("На этой машине не установлен языковой пакет Tesseract для русского")

    monkeypatch.setattr(ocr_module, "_run_tesseract", _raise_ocr_error)
    monkeypatch.setattr(ocr_module, "ProcessPoolExecutor", _FakeExecutor)

    with pytest.raises(OcrError, match="языковой пакет"):
        ocr_module.extract_text_from_scanned_pdf(str(tmp_path / "scan.pdf"))
