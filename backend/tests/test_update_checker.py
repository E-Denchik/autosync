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
                200, {"assets": [{"name": "autosync", "browser_download_url": "http://example/autosync"}]}
            )
        if url == "http://example/autosync":
            return _FakeStreamResponse(payload, headers={"Content-Length": str(total)})
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
                    ]
                },
            )
        if url == "http://example/autosync.deb":
            return _FakeStreamResponse([b"deb-bytes"], headers={"Content-Length": "9"})
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(update_checker.requests, "get", fake_get)

    update_checker.start_download()
    state = _wait_until_phase_leaves("downloading")

    assert state["phase"] == "downloaded"
    assert state["asset_name"] == "autosync-desktop_0.1.0_amd64.deb"


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


def test_consume_pending_update_result_reports_success_when_commit_changed(monkeypatch, tmp_path):
    _fake_build_info(monkeypatch, tmp_path, "new-sha")
    monkeypatch.setenv("AUTOSYNC_DATA_DIR", str(tmp_path))
    marker_path = tmp_path / "pending_update.json"
    marker_path.write_text(json.dumps({"previous_commit": "old-sha", "result_path": None}), encoding="utf-8")

    result = update_checker.consume_pending_update_result()

    assert result == {"success": True, "commit": "new-sha"}
    assert not marker_path.exists()  # маркер одноразовый


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
