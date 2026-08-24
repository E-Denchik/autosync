from datetime import datetime

from app.extensions import db


class Contragent(db.Model):
    __tablename__ = "contragents"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False, unique=True)
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    repair_orders = db.relationship("RepairOrder", back_populates="contragent")
    contracts = db.relationship("Contract", back_populates="contragent")
    hourly_rates = db.relationship("ContragentHourlyRate", back_populates="contragent", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Contragent {self.name} rate={self.hourly_rate}>"


class ContragentHourlyRate(db.Model):
    __tablename__ = "contragent_hourly_rates"

    id = db.Column(db.Integer, primary_key=True)
    contragent_id = db.Column(db.Integer, db.ForeignKey("contragents.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_make = db.Column(db.String(128), nullable=False, index=True)
    # NULL — ставка действует на все модели этой марки, см. тот же
    # комментарий у ContractHourlyRate.vehicle_model.
    vehicle_model = db.Column(db.String(128))
    hourly_rate = db.Column(db.Numeric(10, 2), nullable=False)

    contragent = db.relationship("Contragent", back_populates="hourly_rates")

    def __repr__(self):
        return f"<ContragentHourlyRate {self.vehicle_make} {self.vehicle_model or ''} {self.hourly_rate}>"
