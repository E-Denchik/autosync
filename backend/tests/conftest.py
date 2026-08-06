import shutil
import tempfile

import pytest

from app import create_app
from app.config import Config
from app.extensions import db


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Явно НЕ используем Config.UPLOAD_DIR (~/.autosync/uploads по умолчанию) —
    # тесты не должны трогать реальный каталог данных пользователя.
    UPLOAD_DIR = tempfile.mkdtemp(prefix="autosync-test-uploads-")


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_upload_dir():
    yield
    shutil.rmtree(TestConfig.UPLOAD_DIR, ignore_errors=True)


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


def _create_user(app, email, password, role):
    from app.extensions import db
    from app.models import User, UserRole

    with app.app_context():
        user = User(email=email, role=UserRole(role))
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user.id


def _login_headers(client, email, password):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.get_json()
    token = resp.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers(app, client):
    _create_user(app, "admin@test.local", "adminpass123", "admin")
    return _login_headers(client, "admin@test.local", "adminpass123")


@pytest.fixture
def operator_headers(app, client):
    _create_user(app, "operator@test.local", "operatorpass123", "operator")
    return _login_headers(client, "operator@test.local", "operatorpass123")
