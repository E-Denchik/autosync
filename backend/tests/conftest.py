import os
import shutil
import tempfile

import pytest

from app import create_app
from app.config import Config
from app.extensions import db


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Явно НЕ используем Config.DATA_DIR/UPLOAD_DIR (~/.autosync по умолчанию) —
    # тесты не должны трогать реальный каталог данных пользователя (в т.ч.
    # POST /api/integrations/keys пишет файл прямо в DATA_DIR).
    DATA_DIR = tempfile.mkdtemp(prefix="autosync-test-data-")
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_dir():
    yield
    shutil.rmtree(TestConfig.DATA_DIR, ignore_errors=True)


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def _create_user(app, email, role):
    from app.extensions import db
    from app.models import User, UserRole

    with app.app_context():
        user = User(email=email, role=UserRole(role))
        db.session.add(user)
        db.session.commit()
        return user.id


def _login_headers(client, user_id):
    resp = client.post("/api/auth/login", json={"user_id": user_id})
    assert resp.status_code == 200, resp.get_json()
    token = resp.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(app, client):
    user_id = _create_user(app, "admin@test.local", "admin")
    return _login_headers(client, user_id)


@pytest.fixture
def operator_headers(app, client):
    user_id = _create_user(app, "operator@test.local", "operator")
    return _login_headers(client, user_id)
