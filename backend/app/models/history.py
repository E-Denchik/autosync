from datetime import datetime

from app.extensions import db


class RecordHistory(db.Model):
    """Журнал действий + историчность состояний одновременно.

    Вместо перезаписи состояния сущности (approve/reject заказ-наряда,
    смена цены и т.п.) — каждое изменение закрывает предыдущую запись
    (end_day) и открывает новую (start_day). Один и тот же механизм даёт
    и журнал «когда/что сделано» (это строки сами по себе, упорядоченные
    по start_day), и выборку «каким было состояние сущности в произвольный
    момент времени» (запись, чей интервал [start_day, end_day) накрывает
    нужную дату).

    entity_type/entity_id — не FK: одна таблица журналирует разные типы
    сущностей (заказ-наряды, сопоставления, цены, ...), жёсткая FK на
    конкретную таблицу здесь невозможна и не нужна — история обязана
    пережить даже удаление самой сущности.
    """

    __tablename__ = "record_history"

    id = db.Column(db.Integer, primary_key=True)

    entity_type = db.Column(db.String(64), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.String(32), nullable=False)

    details = db.Column(db.JSON)

    start_day = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    end_day = db.Column(db.DateTime, nullable=True, index=True)  # NULL = текущая версия

    def __repr__(self):
        return f"<RecordHistory {self.entity_type}#{self.entity_id} {self.action} start={self.start_day}>"
