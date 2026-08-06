from datetime import datetime, timedelta

from app.extensions import db
from app.models import User, UserRole
from app.services.history import log_change, query_history


def test_log_change_opens_a_new_current_entry(app):
    with app.app_context():
        entry = log_change("widget", 1, "created")
        db.session.commit()

        assert entry.start_day is not None
        assert entry.end_day is None


def test_log_change_closes_previous_and_opens_new(app):
    with app.app_context():
        first = log_change("widget", 1, "created")
        db.session.commit()
        first_id = first.id

        second = log_change("widget", 1, "updated")
        db.session.commit()

        closed = db.session.get(type(first), first_id)
        assert closed.end_day is not None
        assert second.end_day is None
        assert second.id != first_id


def test_log_change_is_scoped_per_entity(app):
    with app.app_context():
        log_change("widget", 1, "created")
        log_change("widget", 2, "created")
        db.session.commit()

        # изменение widget#1 не должно закрывать открытую запись widget#2
        log_change("widget", 1, "updated")
        db.session.commit()

        open_entries = query_history(entity_type="widget", only_current=True)
        entity_ids = {e.entity_id for e in open_entries}
        assert entity_ids == {1, 2}


def test_query_history_filters_by_action_and_actor(app):
    with app.app_context():
        admin = User(email="actor@test.local", role=UserRole.ADMIN)
        admin.set_password("adminpass123")
        db.session.add(admin)
        db.session.flush()

        log_change("widget", 1, "created", actor=admin)
        log_change("widget", 1, "approved", actor=admin)
        db.session.commit()

        approved_only = query_history(entity_type="widget", action="approved")
        assert len(approved_only) == 1
        assert approved_only[0].action == "approved"

        by_actor = query_history(actor_id=admin.id)
        assert len(by_actor) == 2


def test_query_history_filters_by_date_range(app):
    with app.app_context():
        entry = log_change("widget", 1, "created")
        db.session.commit()
        entry.start_day = datetime.utcnow() - timedelta(days=10)
        db.session.commit()

        recent = query_history(entity_type="widget", start_from=datetime.utcnow() - timedelta(days=1))
        assert recent == []

        older = query_history(entity_type="widget", start_to=datetime.utcnow() - timedelta(days=1))
        assert len(older) == 1


def test_actor_email_survives_actor_deletion(app):
    # actor_email — собственный снимок на уровне приложения, не зависит от
    # того, жив ли ещё сам пользователь или включено ли принудительное
    # соблюдение внешних ключей в конкретной СУБД (у SQLite в тестах оно
    # выключено, ondelete="SET NULL" в модели реально применяет только
    # Postgres — но actor_email переживает удаление в любом случае).
    with app.app_context():
        user = User(email="disappearing@test.local", role=UserRole.OPERATOR)
        user.set_password("operatorpass123")
        db.session.add(user)
        db.session.flush()

        log_change("widget", 1, "created", actor=user)
        db.session.commit()

        db.session.delete(user)
        db.session.commit()

        entries = query_history(entity_type="widget")
        assert entries[0].actor_email == "disappearing@test.local"
