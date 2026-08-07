from datetime import datetime

from app.extensions import db


class NomenclatureEntry(db.Model):
    """Внутренняя номенклатура/склад автосервиса — код, каталожный номер,
    производитель и остатки. НЕ то же самое, что PartMatch (сопоставление
    договор/наряд с прайсом поставщика): это собственный складской учёт
    заказчика (похоже на выгрузку из 1С), источник которого пока открытый
    вопрос — см. PROJECT.md, «Ограничения и допущения».

    Локальная таблица — заполняется вручную, файлом (см.
    services/nomenclature_import.py) или синхронизацией с реальным API,
    когда он будет определён (services/nomenclature_client.py), по аналогии
    с LaborCatalogEntry/AutoDataClient.
    """

    __tablename__ = "nomenclature_entries"

    id = db.Column(db.Integer, primary_key=True)

    code = db.Column(db.String(128), index=True)  # код
    cat_number = db.Column(db.String(128), index=True)  # № кат.
    manufacturer = db.Column(db.String(256))  # производитель
    name = db.Column(db.String(512), nullable=False, index=True)  # номенклатура/наименование
    unit = db.Column(db.String(32))  # единица

    stock_qty = db.Column(db.Numeric(12, 2))  # остаток
    ordered_qty = db.Column(db.Numeric(12, 2))  # заказано
    reserved_qty = db.Column(db.Numeric(12, 2))  # в резерве
    in_production_qty = db.Column(db.Numeric(12, 2))  # в производстве
    warehouse = db.Column(db.String(128))  # склад
    price = db.Column(db.Numeric(10, 2))  # цена

    source = db.Column(db.String(64), default="manual", nullable=False)  # manual / import / api

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<NomenclatureEntry {self.code or self.cat_number} {self.name!r}>"
