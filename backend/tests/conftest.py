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


@pytest.fixture
def admin_headers():
    return {}


@pytest.fixture
def operator_headers():
    return {}
