from datetime import datetime

from app.extensions import db
from app.models.part_match import ConfidenceLevel, ReviewStatus


class LaborLine(db.Model):
    __tablename__ = "labor_lines"

    id = db.Column(db.Integer, primary_key=True)
    repair_order_id = db.Column(db.Integer, db.ForeignKey("repair_orders.id"), nullable=False, index=True)

    description = db.Column(db.String(512), nullable=False)
    qty = db.Column(db.Numeric(6, 2), default=1)

    matched_operation_name = db.Column(db.String(512))
    norm_hours = db.Column(db.Numeric(6, 2))
    hourly_rate = db.Column(db.Numeric(10, 2))
    total_cost = db.Column(db.Numeric(10, 2))

    confidence_level = db.Column(db.Enum(ConfidenceLevel), nullable=False)
    confidence_score = db.Column(db.Float)

    review_status = db.Column(db.Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False)
    reviewed_at = db.Column(db.DateTime)
    manually_edited = db.Column(db.Boolean, default=False, nullable=False)

    raw_match_data = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    repair_order = db.relationship("RepairOrder", back_populates="labor_lines")

    def __repr__(self):
        return f"<LaborLine {self.description!r} -> {self.matched_operation_name} ({self.norm_hours}h)>"
