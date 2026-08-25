import os
import shutil
import tempfile

import pytest

from app import create_app
from app.config import Config
from app.extensions import db
from app.services.builtin_brand_aliases import BUILTIN_BRAND_ALIASES


class TestConfig(Config):
    TESTING = True
    # Явно НЕ используем Config.DATA_DIR/UPLOAD_DIR (~/.autosync по умолчанию) —
    # тесты не должны трогать реальный каталог данных пользователя (в т.ч.
    # POST /api/integrations/keys пишет файл прямо в DATA_DIR).
    DATA_DIR = tempfile.mkdtemp(prefix="autosync-test-data-")
    UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
    # НЕ sqlite:///:memory: — SQLAlchemy для ":memory:" использует один
    # ЕДИНЫЙ общий коннекшн (StaticPool) на всё приложение, а один и тот же
    # sqlite3-коннекшн не рассчитан на одновременные запросы из нескольких
    # потоков: как только сопоставление стало параллельным (см.
    # services/parallel.py — несколько LLM-запросов сразу, каждый в своём
    # потоке), тесты с несколькими позициями в заказ-наряде стабильно
    # зависали намертво (воспроизведено и продиагностировано через py-spy —
    # все потоки стояли внутри sqlite do_execute). Обычный файл — ровно то,
    # что и в реальной сборке (см. app/config.py: Config.SQLALCHEMY_DATABASE_URI),
    # с нормальным пулом соединений (свой коннекшн на поток), где это уже
    # проверено и работает.
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DATA_DIR, "test.db")


@pytest.fixture(scope="session", autouse=True)
def _cleanup_test_data_dir():
    yield
    shutil.rmtree(TestConfig.DATA_DIR, ignore_errors=True)


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        # db.create_all() строит схему из моделей напрямую, БЕЗ прогона
        # Alembic-миграций — а seed BrandAlias живёт в шаге upgrade()
        # миграции b7e3a9c5d1f8, который тут не выполняется. Без этого
        # таблица в тестах была бы пустой, и любой тест на
        # _normalize_brand_label/сопоставление по марке ловил бы "ничего не
        # нашли" вместо реального поведения. BUILTIN_BRAND_ALIASES — тот же
        # источник данных, что и в самой миграции (см. её докстринг).
        from app.models import BrandAlias

        db.session.bulk_insert_mappings(
            BrandAlias,
            [
                {"alias": alias, "canonical_make": canonical, "source": "builtin"}
                for alias, canonical in BUILTIN_BRAND_ALIASES.items()
            ],
        )
        db.session.commit()
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
