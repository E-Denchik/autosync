import enum
from datetime import datetime

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
    name = db.Column(db.String(512), nullable=False)
    qty = db.Column(db.Numeric(12, 2))
    price = db.Column(db.Numeric(12, 2))

    contract = db.relationship("Contract", back_populates="parts")

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
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False)

    contract = db.relationship("Contract", back_populates="hourly_rates")

    def __repr__(self):
        return f"<ContractHourlyRate {self.vehicle_make} {self.hourly_rate}>"
