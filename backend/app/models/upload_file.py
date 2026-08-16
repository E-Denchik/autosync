from datetime import datetime

from app.extensions import db


class ContractFile(db.Model):
    __tablename__ = "contract_files"

    id = db.Column(db.Integer, primary_key=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("contracts.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    contract = db.relationship("Contract", back_populates="extra_files")

    def __repr__(self):
        return f"<ContractFile {self.original_filename}>"


class RepairOrderFile(db.Model):
    __tablename__ = "repair_order_files"

    id = db.Column(db.Integer, primary_key=True)
    repair_order_id = db.Column(db.Integer, db.ForeignKey("repair_orders.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(512), nullable=False)
    storage_path = db.Column(db.String(1024), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    repair_order = db.relationship("RepairOrder", back_populates="extra_files")

    def __repr__(self):
        return f"<RepairOrderFile {self.original_filename}>"
