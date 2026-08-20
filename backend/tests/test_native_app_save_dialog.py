"""SaveDialogApi (js_api-мост для системного диалога "Сохранить как", см.
backend/native_app.py) — импортируется независимо от того, поднято ли
реальное окно (create_file_dialog подменяется фейковым объектом window),
поэтому тест не требует GTK/WebView2 на машине, где гоняются тесты."""

import base64

import native_app


class _FakeWindow:
    def __init__(self, chosen_path=None):
        self.chosen_path = chosen_path
        self.last_file_types = None

    def create_file_dialog(self, dialog_type, save_filename="", file_types=()):
        self.last_file_types = file_types
        return (self.chosen_path,) if self.chosen_path else None


def test_writes_exact_bytes_to_chosen_path(tmp_path):
    target = tmp_path / "saved.xlsx"
    api = native_app.SaveDialogApi()
    api.window = _FakeWindow(chosen_path=str(target))

    content = b"some xlsx bytes \x00\x01\x02"
    result = api.save_file_dialog("suggested.xlsx", base64.b64encode(content).decode())

    assert result == {"ok": True, "path": str(target)}
    assert target.read_bytes() == content


def test_user_cancel_is_not_an_error(tmp_path):
    api = native_app.SaveDialogApi()
    api.window = _FakeWindow(chosen_path=None)

    result = api.save_file_dialog("suggested.xlsx", base64.b64encode(b"x").decode())

    assert result == {"ok": False, "canceled": True}


def test_window_not_ready_returns_error_not_crash():
    api = native_app.SaveDialogApi()
    assert api.window is None

    result = api.save_file_dialog("suggested.xlsx", base64.b64encode(b"x").decode())

    assert result["ok"] is False
    assert "error" in result


def test_valid_file_types_are_passed_through(tmp_path):
    target = tmp_path / "saved.xlsx"
    api = native_app.SaveDialogApi()
    window = _FakeWindow(chosen_path=str(target))
    api.window = window

    api.save_file_dialog(
        "suggested.xlsx", base64.b64encode(b"x").decode(), ["Excel файлы (*.xlsx)", "Все файлы (*.*)"]
    )

    assert window.last_file_types == ("Excel файлы (*.xlsx)", "Все файлы (*.*)")


def test_invalid_file_type_is_dropped_instead_of_breaking_the_whole_dialog(tmp_path):
    """Регрессия: заказчик сообщил, что скачивание/экспорт ЛЮБОГО файла
    выдаёт "файлы is not a valid file filter". Причина — pywebview требует
    строгий формат фильтра ("Описание (*.ext)", только буквы/цифры/пробелы
    в описании) и раньше падал целиком на первой же некорректной строке
    (использованные константы содержали дефис: "Excel-файлы (*.xlsx)").
    Теперь такая строка просто пропускается, а не рушит весь диалог."""
    target = tmp_path / "saved.xlsx"
    api = native_app.SaveDialogApi()
    window = _FakeWindow(chosen_path=str(target))
    api.window = window

    content = b"content"
    result = api.save_file_dialog(
        "suggested.xlsx",
        base64.b64encode(content).decode(),
        ["Excel-файлы (*.xlsx)", "Все файлы (*.*)"],  # первая строка — заведомо невалидная (дефис)
    )

    assert result == {"ok": True, "path": str(target)}
    assert target.read_bytes() == content
    # Невалидный фильтр отброшен, валидный остался.
    assert window.last_file_types == ("Все файлы (*.*)",)


def test_all_file_types_invalid_falls_back_to_no_filter(tmp_path):
    target = tmp_path / "saved.xlsx"
    api = native_app.SaveDialogApi()
    window = _FakeWindow(chosen_path=str(target))
    api.window = window

    result = api.save_file_dialog(
        "suggested.xlsx", base64.b64encode(b"x").decode(), ["Bad-Filter (*.xlsx)", "Also-Bad (*.csv)"]
    )

    assert result["ok"] is True
    assert window.last_file_types == ()
