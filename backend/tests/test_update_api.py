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


def test_install_returns_400_when_not_a_packaged_build(client, monkeypatch):
    def fake_install():
        raise update_checker.UpdateInstallError("Установка обновления доступна только в собранном приложении.")

    monkeypatch.setattr(update_checker, "install_update", fake_install)

    resp = client.post("/api/update/install")
    assert resp.status_code == 400
    assert "собранном приложении" in resp.get_json()["error"]


def test_install_returns_status_installing_on_success(client, monkeypatch):
    monkeypatch.setattr(update_checker, "install_update", lambda: None)

    resp = client.post("/api/update/install")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "installing"
