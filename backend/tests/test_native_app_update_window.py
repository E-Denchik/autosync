"""Открытие отдельного системного окна прогресса обновления (см.
native_app.py: SaveDialogApi.open_update_window / UpdateWindowApi) —
пользователь просил именно системное окно (можно свернуть/закрыть
независимо от главного), а не встроенную панель. webview.create_window
подменяется фейком, поэтому тест не требует GTK/WebView2 на машине."""

import native_app


class _FakeEvent:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self):
        for h in self.handlers:
            h()


class _FakeEvents:
    def __init__(self):
        self.closed = _FakeEvent()


class _FakeWebviewWindow:
    def __init__(self):
        self.events = _FakeEvents()
        self.restored = False
        self.focused = False
        self.destroyed = False

    def restore(self):
        self.restored = True

    def focus(self):
        self.focused = True

    def destroy(self):
        self.destroyed = True


def test_open_update_window_fails_gracefully_before_main_window_ready():
    api = native_app.SaveDialogApi()
    result = api.open_update_window()

    assert result == {"ok": False, "error": "Окно приложения ещё не готово"}


def test_open_update_window_creates_window_with_port_and_token(monkeypatch):
    api = native_app.SaveDialogApi()
    api.backend_port = 5000
    api.session_token = "sekrit-token"

    captured = {}
    fake_window = _FakeWebviewWindow()

    def fake_create_window(title, url, **kwargs):
        captured["title"] = title
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fake_window

    monkeypatch.setattr("webview.create_window", fake_create_window)

    result = api.open_update_window()

    assert result == {"ok": True}
    assert captured["url"] == "http://127.0.0.1:5000/update-progress?token=sekrit-token"
    assert api.update_window is fake_window


def test_open_update_window_reuses_existing_window_instead_of_opening_a_second_one(monkeypatch):
    api = native_app.SaveDialogApi()
    api.backend_port = 5000
    api.session_token = "tok"

    calls = []
    monkeypatch.setattr("webview.create_window", lambda *a, **kw: calls.append(1) or _FakeWebviewWindow())

    api.open_update_window()
    assert len(calls) == 1

    fake_window = api.update_window
    result = api.open_update_window()

    assert len(calls) == 1  # второй клик не создаёт новое окно
    assert fake_window.restored is True
    assert fake_window.focused is True
    assert result == {"ok": True}


def test_update_window_reference_clears_when_window_closed(monkeypatch):
    api = native_app.SaveDialogApi()
    api.backend_port = 5000
    api.session_token = "tok"
    fake_window = _FakeWebviewWindow()
    monkeypatch.setattr("webview.create_window", lambda *a, **kw: fake_window)

    api.open_update_window()
    assert api.update_window is fake_window

    fake_window.events.closed.fire()

    assert api.update_window is None


def test_update_window_api_close_window_destroys_the_window():
    fake_window = _FakeWebviewWindow()
    update_api = native_app.UpdateWindowApi(main_api=native_app.SaveDialogApi())
    update_api.window = fake_window

    result = update_api.close_window()

    assert result == {"ok": True}
    assert fake_window.destroyed is True


def test_update_window_api_close_window_before_ready_does_not_crash():
    update_api = native_app.UpdateWindowApi(main_api=native_app.SaveDialogApi())
    assert update_api.window is None

    result = update_api.close_window()

    assert result == {"ok": True}
