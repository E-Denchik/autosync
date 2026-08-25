import enum
from datetime import datetime

from sqlalchemy.orm import validates

from app.extensions import db


class DocumentProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class Contract(db.Model):
    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256))
    contragent_id = db.Column(db.Integer, db.ForeignKey("contragents.id"), index=True)
    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    # Хэш содержимого загруженного файла(ов) — чтобы при повторной загрузке
    # того же файла (частая причина задвоенных договоров, см. PROJECT.md)
    # переиспользовать уже существующий договор вместо создания копии.
    content_hash = db.Column(db.String(64), index=True)
    status = db.Column(
        db.Enum(DocumentProcessingStatus), default=DocumentProcessingStatus.UPLOADED, nullable=False
    )
    error_message = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    contragent = db.relationship("Contragent", back_populates="contracts")
    repair_orders = db.relationship("RepairOrder", back_populates="contract")
    extra_files = db.relationship("ContractFile", back_populates="contract", cascade="all, delete-orphan")
    parts = db.relationship("ContractPart", back_populates="contract", cascade="all, delete-orphan")
    labor_norms = db.relationship("ContractLaborNorm", back_populates="contract", cascade="all, delete-orphan")
    hourly_rates = db.relationship("ContractHourlyRate", back_populates="contract", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Contract {self.name or self.original_filename} status={self.status}>"


class ContractPart(db.Model):
    __tablename__ = "contract_parts"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    article = db.Column(db.String(128), index=True)
    # article без пробелов/тире и в верхнем регистре (см. matcher.normalize_article)
    # — механик, печатающий заказ-наряд в Excel, форматирует один и тот же
    # артикул иначе, чем каталог поставщика ("234102G000" в наряде против
    # "23410-2G000" в каталоге) — точное совпадение по article это пропускало.
    # Отдельная индексированная колонка, а не REPLACE() в запросе на лету,
    # чтобы сравнение оставалось индексированным SQL-запросом даже на
    # каталогах 50 000+ строк (см. PROJECT.md).
    article_normalized = db.Column(db.String(128), index=True)
    name = db.Column(db.String(512), nullable=False)
    qty = db.Column(db.Numeric(12, 2))
    price = db.Column(db.Numeric(12, 2))
    # Марка, которой принадлежит эта строка — заполняется, когда каталог был
    # многобрендовым файлом (лист "KIA"/"Hyundai"/... — см.
    # document_parser.parse_price_catalog_by_brand). NULL для общих
    # каталогов/расходников без деления по маркам (см. ContractLaborNorm.vehicle_make —
    # тот же приём для нормо-часов).
    vehicle_make = db.Column(db.String(128), index=True)

    contract = db.relationship("Contract", back_populates="parts")

    @validates("article")
    def _sync_article_normalized(self, key, value):
        # Локальный импорт: matcher.py импортирует ContractPart из
        # app.models на уровне модуля — импорт наверху этого файла создал
        # бы цикл. Это НЕ покрывает bulk_insert_mappings/bulk_update_mappings
        # (contract_catalog_import.py) — те идут в обход ORM-событий, там
        # article_normalized выставляется явно.
        from app.services.matcher import normalize_article

        self.article_normalized = normalize_article(value)
        return value

    def __repr__(self):
        return f"<ContractPart {self.article or ''} {self.name}>"


class ContractLaborNorm(db.Model):
    __tablename__ = "contract_labor_norms"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_name = db.Column(db.String(512), nullable=False, index=True)
    vehicle_make = db.Column(db.String(128))
    vehicle_model = db.Column(db.String(128))
    norm_hours = db.Column(db.Numeric(6, 2), nullable=False)

    contract = db.relationship("Contract", back_populates="labor_norms")

    def __repr__(self):
        return f"<ContractLaborNorm {self.operation_name} {self.norm_hours}h>"


class ContractHourlyRate(db.Model):
    __tablename__ = "contract_hourly_rates"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_make = db.Column(db.String(128), nullable=False, index=True)
    # NULL — ставка действует на все модели этой марки. Заполнено — только
    # на конкретную модель: реальный тендерный прайс-лист заказчика даёт
    # РАЗНЫЕ ставки для разных моделей одной марки (Hyundai Accent/Sonata —
    # 720 ₽, Hyundai Tucson/IX35/Santa Fe — 810 ₽) — одной ставки на марку
    # недостаточно, см. app/services/hourly_rate_import.py.
    vehicle_model = db.Column(db.String(128))
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False)

    contract = db.relationship("Contract", back_populates="hourly_rates")

    def __repr__(self):
        return f"<ContractHourlyRate {self.vehicle_make} {self.vehicle_model or ''} {self.hourly_rate}>"
