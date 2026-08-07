import enum
from datetime import datetime

from app.extensions import db


class RepairOrderStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    MATCHING = "matching"
    NEEDS_REVIEW = "needs_review"
    REVIEWED = "reviewed"
    FAILED = "failed"


class RepairOrder(db.Model):
    """Заказ-наряд, сопоставляемый с позициями договора."""

    __tablename__ = "repair_orders"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False, index=True)
    contragent_id = db.Column(db.Integer, db.ForeignKey("contragents.id"), index=True)

    vehicle_make = db.Column(db.String(128))
    vehicle_model = db.Column(db.String(128))
    vehicle_year = db.Column(db.Integer)
    vehicle_vin = db.Column(db.String(32))

    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    status = db.Column(db.Enum(RepairOrderStatus), default=RepairOrderStatus.UPLOADED, nullable=False)
    parsed_lines = db.Column(db.JSON)
    error_message = db.Column(db.Text)

    generated_document_path = db.Column(db.String(1024))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    contract = db.relationship("Contract", back_populates="repair_orders")
    contragent = db.relationship("Contragent", back_populates="repair_orders")
    part_matches = db.relationship(
        "PartMatch", back_populates="repair_order", cascade="all, delete-orphan"
    )
    labor_lines = db.relationship(
        "LaborLine", back_populates="repair_order", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<RepairOrder {self.original_filename} status={self.status}>"
