"""Персистентное хранение ключей внешних API (Ozon Seller/Performance,
сторонний аналитический сервис) — в базе данных (IntegrationSetting), как и
остальные данные приложения, а не в файле/переменных окружения терминала.

Секреты, не резервные данные — но всё равно в той же SQLite-базе, что и
всё остальное: проще для пользователя (один файл данных, а не два),
см. app/models/integration_setting.py.
"""

from __future__ import annotations

import json
import os

from app.config import _bundled_resource
from app.extensions import db
from app.models import IntegrationSetting

ALLOWED_KEYS = [
    "OZON_CLIENT_ID",
    "OZON_API_KEY",
    "OZON_PERFORMANCE_CLIENT_ID",
    "OZON_PERFORMANCE_CLIENT_SECRET",
    "ANALYTICS_PROVIDER_BASE_URL",
    "ANALYTICS_PROVIDER_API_KEY",
    "ALFAAUTO_BASE_URL",
    "ALFAAUTO_LOGIN",
    "ALFAAUTO_PASSWORD",
    "ROSSCO_KEY1",
    "ROSSCO_KEY2",
    "AUTOEURO_LOGIN",
    "AUTOEURO_ACCOUNT_ID",
    "AUTOEURO_API_KEY",
    "MOSKVORECHYE_BASE_URL",
    "MOSKVORECHYE_API_KEY",
]


def load_all() -> dict[str, str]:
    return {row.key: row.value for row in IntegrationSetting.query.all()}


def seed_baked_defaults() -> None:
    if IntegrationSetting.query.count() > 0:
        return
    baked_path = _bundled_resource("app", "_baked_integration_keys.json")
    if not os.path.isfile(baked_path):
        return
    with open(baked_path, "r", encoding="utf-8") as f:
        defaults = json.load(f)
    save_keys(defaults)


def save_keys(updates: dict) -> None:
    """Мержит updates (только ключи из ALLOWED_KEYS, непустые значения)
    поверх уже сохранённых записей."""
    for key in ALLOWED_KEYS:
        value = updates.get(key)
        if not value:
            continue
        row = IntegrationSetting.query.filter_by(key=key).first()
        if row is None:
            db.session.add(IntegrationSetting(key=key, value=value))
        else:
            row.value = value
    db.session.commit()
