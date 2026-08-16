"""Журнал действий / историчность записей — см. app/services/history.py.
Параметризованная выборка для вкладки «История» на фронте."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from app.auth import admin_required
from app.extensions import db
from app.models import RecordHistory
from app.services.history import count_history, query_history
from app.services.pagination import DEFAULT_PER_PAGE, MAX_PER_PAGE, paginated_response, parse_positive_int

bp = Blueprint("history", __name__)
bp.before_request(admin_required(lambda: None))


def _serialize(entry: RecordHistory) -> dict:
    return {
        "id": entry.id,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "action": entry.action,
        "actor_email": entry.actor_email,
        "details": entry.details,
        "start_day": entry.start_day.isoformat(),
        "end_day": entry.end_day.isoformat() if entry.end_day else None,
    }


def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@bp.get("")
def list_history():
    args = request.args
    filters = dict(
        entity_type=args.get("entity_type") or None,
        entity_id=_parse_int(args.get("entity_id")),
        action=args.get("action") or None,
        actor_id=_parse_int(args.get("actor_id")),
        start_from=_parse_date(args.get("start_from")),
        start_to=_parse_date(args.get("start_to")),
        only_current=args.get("only_current") == "true",
    )
    page = parse_positive_int(args.get("page")) or 1
    per_page = min(parse_positive_int(args.get("per_page")) or DEFAULT_PER_PAGE, MAX_PER_PAGE)
    entries = query_history(**filters, limit=per_page, offset=(page - 1) * per_page)
    total = count_history(**filters)
    return paginated_response([_serialize(e) for e in entries], total)


@bp.get("/entity-types")
def list_entity_types():
    """Реальный список entity_type, встречающихся в журнале — фронт строит
    выпадающий фильтр по нему, без хардкода списка сущностей на клиенте."""
    rows = db.session.query(RecordHistory.entity_type).distinct().order_by(RecordHistory.entity_type).all()
    return jsonify([r[0] for r in rows])
