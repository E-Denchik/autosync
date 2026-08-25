from datetime import datetime

from app.extensions import db


class RawImportRow(db.Model):
    """Сырая строка, разобранная из загруженного файла (каталог договора
    ИЛИ заказ-наряд), ДО того, как она стала ContractPart/PartMatch/
    LaborLine — сохраняется сразу после парсинга, до сопоставления, и
    помечается moved после того, как попала в постоянные таблицы.

    Схема НЕ подстраивается под конкретный файл (никаких ALTER TABLE на
    лету под каждую загрузку — это тяжёлая операция на уровне СУБД и не
    даёт никакой реальной пользы, раз перед сопоставлением данные всё
    равно приводятся к одному виду) — вместо этого произвольное количество
    полей ЛЮБОЙ загруженной строки (сколько бы колонок ни было в исходном
    файле) хранится одним JSON-полем в обычной, стабильной таблице. Даёт
    то же самое "нам всё равно, как устроен файл", но без риска и сложности
    динамической схемы:
      - трассируемость: что именно было в файле ДО любой нормализации/
        сопоставления, доступно из БД, а не только "файл лежит на диске";
      - устойчивость: если "перенос в постоянные таблицы" упадёт на
        середине, сырые данные не потеряны и перенос можно повторить не
        перезапрашивая и не перепарсивая файл заново.
    """

    __tablename__ = "raw_import_rows"

    id = db.Column(db.Integer, primary_key=True)
    # Ровно один из двух — откуда эта строка (каталог договора или
    # заказ-наряд); оба nullable, т.к. это не то же самое, что "обязательно
    # оба сразу" — у каждой строки свой единственный источник.
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    repair_order_id = db.Column(db.Integer, db.ForeignKey("repair_orders.id", ondelete="CASCADE"), index=True)
    # "catalog_part" (строка каталога договора) / "order_part" / "order_labor"
    # (запчасть или работа из заказ-наряда) — разные конечные таблицы.
    row_kind = db.Column(db.String(24), nullable=False, index=True)
    source_filename = db.Column(db.String(512))
    row_index = db.Column(db.Integer, nullable=False)  # позиция в исходном файле — для отладки/поддержки
    raw_data = db.Column(db.JSON, nullable=False)  # разобранная строка как есть, сколько бы в ней ни было полей
    status = db.Column(db.String(16), default="staged", nullable=False, index=True)  # staged / moved

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    contract = db.relationship("Contract")
    repair_order = db.relationship("RepairOrder")

    def __repr__(self):
        return f"<RawImportRow {self.row_kind} #{self.row_index} status={self.status}>"
