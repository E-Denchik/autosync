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


@event.listens_for(Engine, "connect")
def _sqlite_wal_mode(dbapi_connection, connection_record):
    """Дефолтный rollback-journal режим SQLite берёт эксклюзивную блокировку
    на файл БД на момент коммита — фоновая задача (импорт каталога/разбор
    заказ-наряда, см. job_queue.py) копит правки ОДНОЙ долгой транзакцией и
    коммитит один раз в конце, и на этот момент читающие запросы (например,
    опрос /status с фронта, см. progress_tracker.py) могут ждать лока.
    WAL позволяет читателям работать, пока идёт запись, и наоборот — на
    single-writer desktop-приложении вроде этого чистый выигрыш, downside
    (лишний -wal/-shm файл рядом с БД) непринципиален."""
    if not hasattr(dbapi_connection, "execute"):
        return  # не SQLite-соединение
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
