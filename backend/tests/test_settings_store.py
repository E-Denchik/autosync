import json

from app.services import settings_store


def _bake(monkeypatch, tmp_path, values):
    path = tmp_path / "_baked_integration_keys.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    monkeypatch.setattr(settings_store, "_bundled_resource", lambda *parts: str(path))


def test_seed_baked_defaults_without_generated_file_is_a_noop(app, monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "_bundled_resource", lambda *parts: str(tmp_path / "missing.json"))

    with app.app_context():
        settings_store.seed_baked_defaults()

        assert settings_store.load_all() == {}


def test_seed_baked_defaults_fills_empty_db(app, monkeypatch, tmp_path):
    _bake(monkeypatch, tmp_path, {"OZON_CLIENT_ID": "baked-cid", "OZON_API_KEY": "baked-key"})

    with app.app_context():
        settings_store.seed_baked_defaults()

        assert settings_store.load_all() == {"OZON_CLIENT_ID": "baked-cid", "OZON_API_KEY": "baked-key"}


def test_seed_baked_defaults_never_touches_a_db_the_customer_already_configured(app, monkeypatch, tmp_path):
    _bake(monkeypatch, tmp_path, {"OZON_CLIENT_ID": "baked-cid", "OZON_API_KEY": "baked-key"})

    with app.app_context():
        settings_store.save_keys({"OZON_CLIENT_ID": "customer-own-id"})
        settings_store.seed_baked_defaults()

        assert settings_store.load_all() == {"OZON_CLIENT_ID": "customer-own-id"}


def test_save_keys_creates_rows(app):
    with app.app_context():
        settings_store.save_keys({"OZON_CLIENT_ID": "cid", "OZON_API_KEY": "key"})

        values = settings_store.load_all()
        assert values == {"OZON_CLIENT_ID": "cid", "OZON_API_KEY": "key"}


def test_save_keys_merges_with_existing_values(app):
    with app.app_context():
        settings_store.save_keys({"OZON_CLIENT_ID": "cid-1"})
        settings_store.save_keys({"OZON_API_KEY": "key-1"})

        assert settings_store.load_all() == {"OZON_CLIENT_ID": "cid-1", "OZON_API_KEY": "key-1"}


def test_save_keys_overwrites_existing_value(app):
    with app.app_context():
        settings_store.save_keys({"OZON_CLIENT_ID": "old"})
        settings_store.save_keys({"OZON_CLIENT_ID": "new"})

        assert settings_store.load_all() == {"OZON_CLIENT_ID": "new"}


def test_save_keys_ignores_disallowed_keys(app):
    with app.app_context():
        settings_store.save_keys({"SECRET_KEY": "hijack", "OZON_CLIENT_ID": "cid"})

        values = settings_store.load_all()
        assert "SECRET_KEY" not in values
        assert values["OZON_CLIENT_ID"] == "cid"


def test_save_keys_skips_empty_values(app):
    with app.app_context():
        settings_store.save_keys({"OZON_CLIENT_ID": "cid", "OZON_API_KEY": ""})

        assert settings_store.load_all() == {"OZON_CLIENT_ID": "cid"}
