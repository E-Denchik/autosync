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

    def __repr__(self):
        return f"<Contragent {self.name} rate={self.hourly_rate}>"
