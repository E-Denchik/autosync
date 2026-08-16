from __future__ import annotations

from app.extensions import db
from app.models import IntegrationSetting

FIELDS = ["COMPANY_NAME", "COMPANY_INN", "COMPANY_ADDRESS", "COMPANY_PHONE"]


def load() -> dict[str, str]:
    rows = IntegrationSetting.query.filter(IntegrationSetting.key.in_(FIELDS)).all()
    values = {row.key: row.value for row in rows}
    return {field: values.get(field, "") for field in FIELDS}


def save(updates: dict) -> None:
    for field in FIELDS:
        if field not in updates:
            continue
        value = (updates.get(field) or "").strip()
        row = IntegrationSetting.query.filter_by(key=field).first()
        if row is None:
            db.session.add(IntegrationSetting(key=field, value=value))
        else:
            row.value = value
    db.session.commit()
