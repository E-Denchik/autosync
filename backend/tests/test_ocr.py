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
