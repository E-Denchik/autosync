"""Журнал действий + историчность состояний (см. app/models/history.py).

Единая точка входа для записи изменений: log_change() закрывает текущую
открытую версию сущности (end_day) и открывает новую (start_day) — вместо
перезаписи состояния. query_history() — параметризованная выборка для
страницы «История» на фронте.
"""

from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models.history import RecordHistory
from app.models.user import User


def log_change(
    entity_type: str,
    entity_id: int,
    action: str,
    actor: User | None = None,
    details: dict | None = None,
) -> RecordHistory:
    """Закрывает текущую открытую (end_day IS NULL) запись истории для
    (entity_type, entity_id), если она есть, и открывает новую. Не делает
    commit — вызывающая сторона обычно уже коммитит само изменение сущности
    следом, чтобы запись истории была атомарна с ним."""
    now = datetime.utcnow()

    current = RecordHistory.query.filter_by(
        entity_type=entity_type, entity_id=entity_id, end_day=None
    ).first()
    if current is not None:
        current.end_day = now

    entry = RecordHistory(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else None,
        details=details,
        start_day=now,
        end_day=None,
    )
    db.session.add(entry)
    return entry


def query_history(
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    actor_id: int | None = None,
    start_from: datetime | None = None,
    start_to: datetime | None = None,
    only_current: bool = False,
    limit: int = 200,
) -> list[RecordHistory]:
    """Параметризованный поиск по журналу — start_from/start_to фильтруют
    по start_day (когда запись стала действующей), only_current оставляет
    только ещё не закрытые (end_day IS NULL) записи — то есть текущее
    состояние сущностей, а не полную историю их изменений."""
    query = RecordHistory.query

    if entity_type:
        query = query.filter(RecordHistory.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(RecordHistory.entity_id == entity_id)
    if action:
        query = query.filter(RecordHistory.action == action)
    if actor_id is not None:
        query = query.filter(RecordHistory.actor_id == actor_id)
    if start_from is not None:
        query = query.filter(RecordHistory.start_day >= start_from)
    if start_to is not None:
        query = query.filter(RecordHistory.start_day <= start_to)
    if only_current:
        query = query.filter(RecordHistory.end_day.is_(None))

    return query.order_by(RecordHistory.start_day.desc()).limit(limit).all()
