from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _sqlite_unicode_aware_case_folding(dbapi_connection, connection_record):
    """SQLite's built-in lower()/upper() only case-fold ASCII — 'Тормозной'
    stays unchanged, silently breaking ilike()-based search for Cyrillic
    (и любой другой не-ASCII) текста. Product-названия здесь всегда
    русские, поэтому переопределяем lower()/upper() на Python-реализацию
    (Unicode-aware) для каждого нового соединения."""
    if not hasattr(dbapi_connection, "create_function"):
        return  # не SQLite-соединение
    dbapi_connection.create_function("lower", 1, lambda s: s.lower() if s is not None else None)
    dbapi_connection.create_function("upper", 1, lambda s: s.upper() if s is not None else None)
