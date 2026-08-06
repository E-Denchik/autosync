from datetime import datetime

from app.extensions import db


class IntegrationSetting(db.Model):
    """Ключи внешних API (Ozon Seller/Performance, аналитика конкурентов) —
    в базе данных, как и остальные данные приложения, а не в файле на диске.
    Секреты: значения никогда не отдаются обратно клиенту через API, см.
    app/api/integrations.py — GET /status возвращает только "настроено:
    да/нет" (app/services/settings_store.py)."""

    __tablename__ = "integration_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<IntegrationSetting {self.key}>"
