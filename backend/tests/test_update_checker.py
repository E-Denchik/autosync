import json
import os
import sys

from app.services import update_checker


class _FakeResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self.ok = status_code < 400
        self._json = json_data
        self.text = str(json_data)

    def json(self):
        return self._json


def _fake_build_info(monkeypatch, tmp_path, commit):
    import json

    path = tmp_path / "_build_info.json"
    path.write_text(json.dumps({"commit": commit}), encoding="utf-8")
    monkeypatch.setattr(update_checker, "_bundled_resource", lambda *parts: str(path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_get_current_commit_returns_none_when_not_frozen(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert update_checker.get_current_commit() is None


def test_get_current_commit_returns_none_without_build_info_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(update_checker, "_bundled_resource", lambda *parts: str(tmp_path / "missing.json"))

    assert update_checker.get_current_commit() is None


def test_get_current_commit_reads_baked_commit(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "abc123")

    assert update_checker.get_current_commit() == "abc123"


def test_check_for_update_reports_up_to_date_when_commits_match(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "same-sha")

    def fake_get(url, headers=None, timeout=None):
        assert "refs/tags/latest" in url
        return _FakeResponse(200, {"object": {"sha": "same-sha"}})

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    result = update_checker.check_for_update()
    assert result == {
        "update_available": False,
        "current_commit": "same-sha",
        "latest_commit": "same-sha",
        "changes": [],
    }


def test_check_for_update_reports_changes_from_compare(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "old-sha")

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("refs/tags/latest"):
            return _FakeResponse(200, {"object": {"sha": "new-sha"}})
        if "compare/old-sha...new-sha" in url:
            return _FakeResponse(
                200,
                {
                    "commits": [
                        {"commit": {"message": "Fix nomenclature validation\n\nlonger body"}},
                        {"commit": {"message": "Add update checker"}},
                    ]
                },
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    result = update_checker.check_for_update()
    assert result["update_available"] is True
    assert result["current_commit"] == "old-sha"
    assert result["latest_commit"] == "new-sha"
    assert result["changes"] == ["Fix nomenclature validation", "Add update checker"]


def test_check_for_update_raises_clean_error_when_repo_not_public_yet(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "some-sha")

    def fake_get(url, headers=None, timeout=None):
        return _FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    try:
        update_checker.check_for_update()
        assert False, "expected UpdateCheckError"
    except update_checker.UpdateCheckError as exc:
        assert "приватный" in str(exc) or "404" not in str(exc)


def test_check_for_update_without_build_info_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(update_checker, "_bundled_resource", lambda *parts: str(tmp_path / "missing.json"))

    try:
        update_checker.check_for_update()
        assert False, "expected UpdateCheckError"
    except update_checker.UpdateCheckError:
        pass


def test_start_download_requires_frozen_build(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    try:
        update_checker.start_download()
        assert False, "expected UpdateInstallError"
    except update_checker.UpdateInstallError as exc:
        assert "собранном приложении" in str(exc)


def test_apply_update_requires_frozen_build(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    try:
        update_checker.apply_update()
        assert False, "expected UpdateInstallError"
    except update_checker.UpdateInstallError as exc:
        assert "собранном приложении" in str(exc)


class _FakeStreamResponse:
    def __init__(self, chunks, headers=None):
        self.ok = True
        self.headers = headers or {}
        self._chunks = chunks

    def iter_content(self, chunk_size=None):
        return iter(self._chunks)


def _wait_until_phase_leaves(exclude, timeout=2.0):
    import time as _time

    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        state = update_checker.get_download_state()
        if state["phase"] != exclude:
            return state
        _time.sleep(0.01)
    raise AssertionError(f"download did not leave phase {exclude!r} within {timeout}s")


def _reset_download_state():
    update_checker._set_state(
        phase="idle", downloaded_bytes=0, total_bytes=0, speed_bytes_per_sec=0.0, error=None,
        asset_path=None, asset_name=None,
    )
    update_checker._cancel_event.clear()


def test_start_download_completes_and_reports_final_progress(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/home/user/autosync")

    payload = [b"x" * 1024, b"y" * 2048]
    total = sum(len(c) for c in payload)

    def fake_get(url, headers=None, timeout=None, stream=None):
        if "releases/tags/latest" in url:
            return _FakeResponse(
                200,
                {
                    "assets": [
                        {"name": "autosync", "browser_download_url": "http://example/autosync"},
                        {"name": "SHA256SUMS.txt", "browser_download_url": "http://example/SHA256SUMS.txt"},
                    ]
                },
            )
        if url == "http://example/autosync":
            return _FakeStreamResponse(payload, headers={"Content-Length": str(total)})
        if url == "http://example/SHA256SUMS.txt":
            return _FakeResponse(
                200, "3b4cedeece31fc04a81e748a562921a77dc9636517577c3ddb68e27e08e99289  native-linux/autosync\n"
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    update_checker.start_download()
    state = _wait_until_phase_leaves("downloading")

    assert state["phase"] == "downloaded"
    assert state["downloaded_bytes"] == total
    assert state["total_bytes"] == total
    assert os.path.isfile(state["asset_path"])
    with open(state["asset_path"], "rb") as f:
        assert f.read() == b"".join(payload)


def test_start_download_picks_deb_asset_for_deb_install(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/opt/autosync/autosync")

    def fake_get(url, headers=None, timeout=None, stream=None):
        if "releases/tags/latest" in url:
            return _FakeResponse(
                200,
                {
                    "assets": [
                        {"name": "autosync", "browser_download_url": "http://example/autosync"},
                        {
                            "name": "autosync-desktop_0.1.0_amd64.deb",
                            "browser_download_url": "http://example/autosync.deb",
                        },
                        {"name": "SHA256SUMS.txt", "browser_download_url": "http://example/SHA256SUMS.txt"},
                    ]
                },
            )
        if url == "http://example/autosync.deb":
            return _FakeStreamResponse([b"deb-bytes"], headers={"Content-Length": "9"})
        if url == "http://example/SHA256SUMS.txt":
            return _FakeResponse(
                200,
                "3adc870b6595ccbffaa9ccaa6fa5653652136fbeea99ffd754c52960bd0b9ea9  "
                "autosync-desktop_0.1.0_amd64.deb\n",
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    update_checker.start_download()
    state = _wait_until_phase_leaves("downloading")

    assert state["phase"] == "downloaded"
    assert state["asset_name"] == "autosync-desktop_0.1.0_amd64.deb"


def test_start_download_fails_and_deletes_file_on_checksum_mismatch(monkeypatch, tmp_path):
    """Регрессия: раньше скачанный файл ставился (на Linux — через pkexec
    ROOT'ом) без единой проверки целостности — повреждённая при скачивании
    или подменённая на сервере раздачи сборка ставилась бы как есть."""
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/home/user/autosync")

    def fake_get(url, headers=None, timeout=None, stream=None):
        if "releases/tags/latest" in url:
            return _FakeResponse(
                200,
                {
                    "assets": [
                        {"name": "autosync", "browser_download_url": "http://example/autosync"},
                        {"name": "SHA256SUMS.txt", "browser_download_url": "http://example/SHA256SUMS.txt"},
                    ]
                },
            )
        if url == "http://example/autosync":
            return _FakeStreamResponse([b"actual-content"], headers={"Content-Length": "14"})
        if url == "http://example/SHA256SUMS.txt":
            # Контрольная сумма для ДРУГОГО содержимого — не совпадёт с тем,
            # что реально скачано.
            return _FakeResponse(200, "0" * 64 + "  native-linux/autosync\n")
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    update_checker.start_download()
    state = _wait_until_phase_leaves("downloading")

    assert state["phase"] == "error"
    assert "контрольная сумма" in state["error"].lower() or "повреждён" in state["error"].lower()


def test_start_download_fails_when_checksums_file_missing_from_release(monkeypatch, tmp_path):
    """Отсутствие SHA256SUMS.txt в релизе (например, старый релиз, собранный
    до появления проверки) должно так же останавливать установку, как и
    несовпадение — не откатываться на "разрешить, раз нечего сверить"."""
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/home/user/autosync")

    def fake_get(url, headers=None, timeout=None, stream=None):
        if "releases/tags/latest" in url:
            return _FakeResponse(
                200, {"assets": [{"name": "autosync", "browser_download_url": "http://example/autosync"}]}
            )
        if url == "http://example/autosync":
            return _FakeStreamResponse([b"some-content"], headers={"Content-Length": "12"})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    update_checker.start_download()
    state = _wait_until_phase_leaves("downloading")

    assert state["phase"] == "error"
    assert "не найдена" in state["error"].lower()


def test_start_download_sets_error_state_when_asset_missing(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/home/user/autosync")
    monkeypatch.setattr(
        update_checker.requests,
        "get",
        lambda url, headers=None, timeout=None, stream=None: _FakeResponse(200, {"assets": []}),
    )

    update_checker.start_download()
    state = _wait_until_phase_leaves("downloading")

    assert state["phase"] == "error"
    assert "бинарник Linux" in state["error"]


def test_cancel_download_stops_in_progress_download(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/home/user/autosync")

    import time as _time

    def slow_chunks():
        for _ in range(50):
            _time.sleep(0.02)
            yield b"x" * 1024

    def fake_get(url, headers=None, timeout=None, stream=None):
        if "releases/tags/latest" in url:
            return _FakeResponse(
                200, {"assets": [{"name": "autosync", "browser_download_url": "http://example/autosync"}]}
            )
        return _FakeStreamResponse(slow_chunks(), headers={"Content-Length": "51200"})

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    update_checker.start_download()
    import time as _time2

    _time2.sleep(0.05)  # даём скачиванию реально начаться
    update_checker.cancel_download()

    state = _wait_until_phase_leaves("downloading")
    assert state["phase"] == "canceled"


def test_cancel_download_discards_already_downloaded_file(monkeypatch, tmp_path):
    _reset_download_state()
    asset_path = tmp_path / "autosync-setup-0.1.0.exe"
    asset_path.write_bytes(b"data")
    update_checker._set_state(phase="downloaded", asset_path=str(asset_path), asset_name=asset_path.name)

    update_checker.cancel_download()

    state = update_checker.get_download_state()
    assert state["phase"] == "idle"
    assert not asset_path.exists()


def test_apply_update_requires_downloaded_phase(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")

    try:
        update_checker.apply_update()
        assert False, "expected UpdateInstallError"
    except update_checker.UpdateInstallError as exc:
        assert "Сначала нужно скачать" in str(exc)


def test_apply_update_rejects_unsupported_platform(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "old-sha")
    asset_path = tmp_path / "autosync"
    asset_path.write_bytes(b"data")
    update_checker._set_state(phase="downloaded", asset_path=str(asset_path), asset_name="autosync")
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Darwin")

    try:
        update_checker.apply_update()
        assert False, "expected UpdateInstallError"
    except update_checker.UpdateInstallError as exc:
        assert "Darwin" in str(exc)
    assert update_checker.get_download_state()["phase"] == "error"


def test_apply_update_linux_writes_marker_and_launches_detached_script(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "before-update-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Linux")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: "/home/user/autosync")
    monkeypatch.setattr(update_checker, "_schedule_exit", lambda *a, **kw: None)

    asset_path = tmp_path / "autosync-new"
    asset_path.write_bytes(b"data")
    update_checker._set_state(phase="downloaded", asset_path=str(asset_path), asset_name="autosync")

    captured = {}
    monkeypatch.setattr(
        update_checker.subprocess, "Popen", lambda *a, **kw: captured.setdefault("args", a) or captured.setdefault("kwargs", kw)
    )

    update_checker.apply_update()

    assert update_checker.get_download_state()["phase"] == "applying"
    marker_path = os.path.join(str(tmp_path), "pending_update.json")
    assert os.path.isfile(marker_path)
    with open(marker_path, "r", encoding="utf-8") as f:
        marker = json.load(f)
    assert marker["previous_commit"] == "before-update-sha"
    assert "args" in captured  # detached apply-script процесс реально запущен


def test_apply_update_windows_writes_powershell_script_and_launches_detached(monkeypatch, tmp_path):
    """_apply_windows раньше не имел тестового покрытия вовсе. Проверяем, что
    вместо .bat пишется .ps1 (см. update_checker.py про причину — mbcs ломает
    кириллицу в пути без BOM), с точным отслеживанием PID через
    Start-Process -PassThru, а не сопоставлением по имени образа."""
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "before-update-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Windows")
    monkeypatch.setattr(update_checker, "_running_binary_path", lambda: r"C:\Users\Иван\AppData\Local\AutoSync\autosync.exe")
    monkeypatch.setattr(update_checker, "_schedule_exit", lambda *a, **kw: None)
    # DETACHED_PROCESS/CREATE_NEW_PROCESS_GROUP существуют только на реальной
    # Windows — raising=False позволяет завести их и на Linux, где гоняются тесты.
    monkeypatch.setattr(update_checker.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(update_checker.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)

    asset_path = tmp_path / "autosync-setup-1.2.3.exe"
    asset_path.write_bytes(b"data")
    update_checker._set_state(phase="downloaded", asset_path=str(asset_path), asset_name=asset_path.name)

    captured = {}
    monkeypatch.setattr(
        update_checker.subprocess,
        "Popen",
        lambda *a, **kw: captured.setdefault("args", a) or captured.setdefault("kwargs", kw),
    )

    update_checker.apply_update()

    assert update_checker.get_download_state()["phase"] == "applying"
    assert "args" in captured
    popen_args = captured["args"][0]
    assert popen_args[0] == "powershell"
    script_path = popen_args[-1]
    assert script_path.endswith(".ps1")

    content = open(script_path, "r", encoding="utf-8-sig").read()
    assert "/SILENT" in content
    assert "/CLOSEAPPLICATIONS" in content
    assert "Start-Process" in content
    assert "-PassThru" in content
    assert "Get-Process -Id $newProc.Id" in content
    assert "relaunch_failed" in content
    assert "Иван" in content  # кириллица в пути дошла до скрипта не побитой


def test_apply_update_windows_rejects_non_installer_filename(monkeypatch, tmp_path):
    _reset_download_state()
    _fake_build_info(monkeypatch, tmp_path, "before-update-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(update_checker.platform, "system", lambda: "Windows")

    asset_path = tmp_path / "not-an-installer.exe"
    asset_path.write_bytes(b"data")
    update_checker._set_state(phase="downloaded", asset_path=str(asset_path), asset_name=asset_path.name)

    try:
        update_checker.apply_update()
        assert False, "expected UpdateInstallError"
    except update_checker.UpdateInstallError as exc:
        assert "установщик Windows" in str(exc)


def test_consume_pending_update_result_reports_success_when_commit_changed(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "new-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    marker_path = tmp_path / "pending_update.json"
    marker_path.write_text(json.dumps({"previous_commit": "old-sha", "result_path": None}), encoding="utf-8")

    result = update_checker.consume_pending_update_result()

    assert result == {"success": True, "commit": "new-sha"}
    assert not marker_path.exists()  # маркер одноразовый


def test_consume_pending_update_result_handles_bom_from_windows_powershell(monkeypatch, tmp_path):
    """Регрессия: install_result.txt на Windows пишет PowerShell
    (Set-Content -Encoding utf8), а Windows PowerShell 5.1 в режиме "utf8"
    всегда добавляет BOM. С обычным open(..., encoding="utf-8") это давало
    exit_code "\\ufeff0" вместо "0" — успешную (код 0) установку было не
    отличить от неудачной, потому что str.strip() BOM не убирает."""
    _fake_build_info(monkeypatch, tmp_path, "same-sha")  # коммит НЕ поменялся — как будто откат/неудача
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    marker_path = tmp_path / "pending_update.json"
    result_path = tmp_path / "install_result.txt"
    result_path.write_bytes("0".encode("utf-8-sig"))  # ровно то, что пишет Set-Content -Encoding utf8
    marker_path.write_text(
        json.dumps({"previous_commit": "same-sha", "result_path": str(result_path)}), encoding="utf-8"
    )

    result = update_checker.consume_pending_update_result()

    assert result["exit_code"] == "0"
    assert "версия приложения не изменилась" in result["message"]


def test_consume_pending_update_result_reports_failure_when_commit_unchanged(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "same-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    marker_path = tmp_path / "pending_update.json"
    result_path = tmp_path / "install_result.txt"
    result_path.write_text("1\n", encoding="utf-8")
    marker_path.write_text(
        json.dumps({"previous_commit": "same-sha", "result_path": str(result_path)}), encoding="utf-8"
    )

    result = update_checker.consume_pending_update_result()

    assert result["success"] is False
    assert result["exit_code"] == "1"
    assert "код 1" in result["message"]
    assert not marker_path.exists()
    assert not result_path.exists()


def test_consume_pending_update_result_returns_none_without_marker(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    assert update_checker.consume_pending_update_result() is None


def test_consume_pending_update_result_reports_rollback_when_new_binary_would_not_start(monkeypatch, tmp_path):
    """Регрессия: после обновления новый бинарник может не запуститься (см.
    _apply_linux, ветка не-.deb) — тогда установочный скрипт сам возвращает
    старую рабочую версию и дописывает вторую строку "rolled_back" в
    install_result.txt. Раньше это выглядело бы как обычная "установка не
    применилась" без объяснения, что приложение вообще-то уже само себя
    починило."""
    _fake_build_info(monkeypatch, tmp_path, "same-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    marker_path = tmp_path / "pending_update.json"
    result_path = tmp_path / "install_result.txt"
    result_path.write_text("0\nrolled_back\n", encoding="utf-8")
    marker_path.write_text(
        json.dumps({"previous_commit": "same-sha", "result_path": str(result_path)}), encoding="utf-8"
    )

    result = update_checker.consume_pending_update_result()

    assert result["success"] is False
    assert result["exit_code"] == "0"
    assert "вернулось к предыдущей" in result["message"]


def test_consume_pending_update_result_reports_relaunch_failed_without_rollback(monkeypatch, tmp_path):
    """Та же ситуация, но на .deb/Windows-ветке, где автоматического отката
    нет (см. _apply_linux/_apply_windows) — сообщение должно отличаться от
    rolled_back, чтобы не вводить в заблуждение, будто всё уже само
    исправилось."""
    _fake_build_info(monkeypatch, tmp_path, "same-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    marker_path = tmp_path / "pending_update.json"
    result_path = tmp_path / "install_result.txt"
    result_path.write_text("0\nrelaunch_failed\n", encoding="utf-8")
    marker_path.write_text(
        json.dumps({"previous_commit": "same-sha", "result_path": str(result_path)}), encoding="utf-8"
    )

    result = update_checker.consume_pending_update_result()

    assert result["success"] is False
    assert "не запустилась" in result["message"]
    assert "вернулось к предыдущей" not in result["message"]


def test_relaunch_env_strips_pyinstaller_bootstrap_vars(monkeypatch):
    monkeypatch.setenv("_MEIPASS2", "/tmp/_MEIxxxxx")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "/tmp/_MEIxxxxx")
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "/some/path")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEIxxxxx")
    monkeypatch.setenv("SOME_OTHER_VAR", "keep-me")

    env = update_checker._relaunch_env()

    assert "_MEIPASS2" not in env
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert "_PYI_ARCHIVE_FILE" not in env
    assert "LD_LIBRARY_PATH" not in env
    assert env["SOME_OTHER_VAR"] == "keep-me"
