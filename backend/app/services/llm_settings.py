"""Выбор LLM-модели администратором — хранится одной строкой в БД, поэтому
переживает перезапуск приложения (это обычная таблица, а не файл/переменная
окружения).

Выбор автоматически сбрасывается, если ранее выбранной модели больше нет
среди того, что реально видит llm-service (см. discover_ollama/
discover_lmstudio в llm-service/server.py) — то есть она была удалена с
диска. Пока модель видна — выбор переживает сколько угодно сессий."""

from __future__ import annotations

from app.extensions import db
from app.models.llm_setting import LLMModelSelection

SELECTION_ID = 1


def get_selection() -> LLMModelSelection | None:
    return db.session.get(LLMModelSelection, SELECTION_ID)


def set_selection(provider: str, model_name: str) -> LLMModelSelection:
    row = get_selection()
    if row is None:
        row = LLMModelSelection(id=SELECTION_ID, provider=provider, model_name=model_name)
        db.session.add(row)
    else:
        row.provider = provider
        row.model_name = model_name
    db.session.commit()
    return row


def clear_selection() -> None:
    row = get_selection()
    if row is not None:
        db.session.delete(row)
        db.session.commit()


def is_known_model(discovery: dict, provider: str, model_name: str) -> bool:
    """discovery — то, что вернул llm-service GET /models (см. app/api/llm.py)."""
    provider_info = discovery.get("providers", {}).get(provider)
    if not provider_info:
        return False
    return any(m["name"] == model_name for m in provider_info.get("models", []))
