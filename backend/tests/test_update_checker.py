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


def test_install_update_requires_frozen_build(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)

    try:
        update_checker.install_update()
        assert False, "expected UpdateInstallError"
    except update_checker.UpdateInstallError as exc:
        assert "собранном приложении" in str(exc)


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
