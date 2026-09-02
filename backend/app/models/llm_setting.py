from datetime import datetime

from app.extensions import db


class LLMModelSelection(db.Model):
    """Какую модель использовать для всех LLM-вызовов — локально скачанную
    (Ollama, LM Studio) или облачную (vsegpt.ru) — выбирает администратор
    в UI, хранится одной строкой (id=1), переживает перезапуски. См.
    app/services/llm_settings.py — выбор автоматически сбрасывается, если
    модель пропала из discovery (была удалена с диска, либо для vsegpt.ru —
    ключ убрали/стал невалиден)."""

    __tablename__ = "llm_model_selection"

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(32), nullable=False)
    model_name = db.Column(db.String(255), nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
