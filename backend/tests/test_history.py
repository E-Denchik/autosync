from datetime import datetime, timedelta

from app.extensions import db
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


def test_query_history_filters_by_action(app):
    with app.app_context():
        log_change("widget", 1, "created")
        log_change("widget", 1, "approved")
        db.session.commit()

        approved_only = query_history(entity_type="widget", action="approved")
        assert len(approved_only) == 1
        assert approved_only[0].action == "approved"


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
