from datetime import datetime

from app.extensions import db


class RecordHistory(db.Model):
    """Журнал действий + историчность состояний одновременно.

    Вместо перезаписи состояния сущности (approve/reject заказ-наряда,
    смена цены, создание/удаление пользователя и т.п.) — каждое изменение
    закрывает предыдущую запись (end_day) и открывает новую (start_day).
    Один и тот же механизм даёт и журнал «кто/когда/что сделал» (это
    строки сами по себе, упорядоченные по start_day), и выборку «каким
    было состояние сущности в произвольный момент времени» (запись, чей
    интервал [start_day, end_day) накрывает нужную дату).

    entity_type/entity_id — не FK: одна таблица журналирует разные типы
    сущностей (заказ-наряды, сопоставления, цены, пользователей, ...),
    жёсткая FK на конкретную таблицу здесь невозможна и не нужна — история
    обязана пережить даже удаление самой сущности (см. actor_email —
    по той же причине снимок, а не только FK на users).
    """

    __tablename__ = "record_history"

    id = db.Column(db.Integer, primary_key=True)

    entity_type = db.Column(db.String(64), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.String(32), nullable=False)

    # ondelete="SET NULL" — иначе удаление пользователя, который когда-либо
    # был actor'ом хоть одной записи истории (approve/reject и т.п.),
    # упёрлось бы в нарушение внешнего ключа. actor_email — снимок именно
    # на этот случай: личность в истории не теряется, даже если сам
    # пользователь и FK на него уже исчезли.
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email = db.Column(db.String(255))

    details = db.Column(db.JSON)

    start_day = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    end_day = db.Column(db.DateTime, nullable=True, index=True)  # NULL = текущая версия

    actor = db.relationship("User")

    def __repr__(self):
        return f"<RecordHistory {self.entity_type}#{self.entity_id} {self.action} start={self.start_day}>"
