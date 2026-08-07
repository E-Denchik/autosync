from datetime import datetime

from app.extensions import db


class LaborCatalogEntry(db.Model):
    __tablename__ = "labor_catalog_entries"

    id = db.Column(db.Integer, primary_key=True)
    vehicle_make = db.Column(db.String(128), nullable=False, index=True)
    vehicle_model = db.Column(db.String(128), index=True)
    operation_name = db.Column(db.String(512), nullable=False)
    norm_hours = db.Column(db.Numeric(6, 2), nullable=False)
    source = db.Column(db.String(64), default="manual", nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<LaborCatalogEntry {self.vehicle_make}/{self.vehicle_model} {self.operation_name} {self.norm_hours}h>"
