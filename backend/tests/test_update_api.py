from app.services import update_checker


def test_check_returns_502_with_message_on_github_error(client, monkeypatch):
    def fake_check():
        raise update_checker.UpdateCheckError("репозиторий приватный")

    monkeypatch.setattr(update_checker, "check_for_update", fake_check)

    resp = client.get("/api/update/check")
    assert resp.status_code == 502
    assert "приватный" in resp.get_json()["error"]


def test_check_reports_frozen_flag_alongside_result(client, monkeypatch):
    monkeypatch.setattr(
        update_checker,
        "check_for_update",
        lambda: {"update_available": False, "current_commit": "a", "latest_commit": "a", "changes": []},
    )
    monkeypatch.setattr(update_checker, "is_frozen", lambda: True)

    resp = client.get("/api/update/check")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["update_available"] is False
    assert body["frozen"] is True


def test_download_returns_400_when_not_a_packaged_build(client, monkeypatch):
    def fake_start_download():
        raise update_checker.UpdateInstallError("Установка обновления доступна только в собранном приложении.")

    monkeypatch.setattr(update_checker, "start_download", fake_start_download)

    resp = client.post("/api/update/download")
    assert resp.status_code == 400
    assert "собранном приложении" in resp.get_json()["error"]


def test_download_returns_current_state_on_success(client, monkeypatch):
    monkeypatch.setattr(update_checker, "start_download", lambda: None)
    monkeypatch.setattr(update_checker, "get_download_state", lambda: {"phase": "downloading"})

    resp = client.post("/api/update/download")
    assert resp.status_code == 200
    assert resp.get_json()["phase"] == "downloading"


def test_progress_returns_current_download_state(client, monkeypatch):
    monkeypatch.setattr(
        update_checker,
        "get_download_state",
        lambda: {"phase": "downloading", "downloaded_bytes": 1024, "total_bytes": 4096},
    )

    resp = client.get("/api/update/progress")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["downloaded_bytes"] == 1024
    assert body["total_bytes"] == 4096


def test_cancel_calls_cancel_download_and_returns_state(client, monkeypatch):
    calls = []
    monkeypatch.setattr(update_checker, "cancel_download", lambda: calls.append(True))
    monkeypatch.setattr(update_checker, "get_download_state", lambda: {"phase": "canceled"})

    resp = client.post("/api/update/cancel")
    assert resp.status_code == 200
    assert resp.get_json()["phase"] == "canceled"
    assert calls == [True]


def test_apply_returns_400_when_nothing_downloaded(client, monkeypatch):
    def fake_apply():
        raise update_checker.UpdateInstallError("Сначала нужно скачать обновление.")

    monkeypatch.setattr(update_checker, "apply_update", fake_apply)

    resp = client.post("/api/update/apply")
    assert resp.status_code == 400
    assert "скачать" in resp.get_json()["error"]


def test_apply_returns_status_applying_on_success(client, monkeypatch):
    monkeypatch.setattr(update_checker, "apply_update", lambda: None)

    resp = client.post("/api/update/apply")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "applying"


def test_pending_result_returns_null_when_nothing_pending(client, monkeypatch):
    monkeypatch.setattr(update_checker, "consume_pending_update_result", lambda: None)

    resp = client.get("/api/update/pending-result")
    assert resp.status_code == 200
    assert resp.get_json() is None


def test_pending_result_returns_previous_attempt_outcome(client, monkeypatch):
    monkeypatch.setattr(
        update_checker,
        "consume_pending_update_result",
        lambda: {"success": False, "exit_code": "1", "message": "Установка обновления завершилась с ошибкой (код 1)."},
    )

    resp = client.get("/api/update/pending-result")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is False
    assert "код 1" in body["message"]
