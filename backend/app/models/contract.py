import enum
from datetime import datetime

from app.extensions import db


class DocumentProcessingStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PARSING = "parsing"
    PARSED = "parsed"
    FAILED = "failed"


class Contract(db.Model):
    """Загруженный договор (Excel/PDF) со списком запчастей."""

    __tablename__ = "contracts"

    id = db.Column(db.Integer, primary_key=True)
    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    status = db.Column(
        db.Enum(DocumentProcessingStatus), default=DocumentProcessingStatus.UPLOADED, nullable=False
    )
    parsed_lines = db.Column(db.JSON)  # список позиций после парсинга: [{article, name, qty, price}, ...]
    error_message = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    repair_orders = db.relationship("RepairOrder", back_populates="contract")

    def __repr__(self):
        return f"<Contract {self.original_filename} status={self.status}>"
