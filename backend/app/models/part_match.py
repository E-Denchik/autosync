import enum
from datetime import datetime

from app.extensions import db


class ConfidenceLevel(str, enum.Enum):
    """LLM-догадка никогда не должна выглядеть так же надёжно, как точное
    совпадение по API поставщика — фронт обязан визуально различать эти статусы.
    """

    EXACT = "exact"  # точное совпадение артикула
    CROSS_REF = "cross_ref"  # найдено через кросс-номера поставщика
    LLM_GUESS = "llm_guess"  # fallback: сопоставление LLM по названию


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PartMatch(db.Model):
    """Сопоставление позиции договора с позицией заказ-наряда/поставщика."""

    __tablename__ = "part_matches"

    id = db.Column(db.Integer, primary_key=True)
    repair_order_id = db.Column(db.Integer, db.ForeignKey("repair_orders.id"), nullable=False, index=True)

    contract_article = db.Column(db.String(128))
    contract_name = db.Column(db.String(512))

    matched_article = db.Column(db.String(128))
    matched_name = db.Column(db.String(512))
    matched_price = db.Column(db.Numeric(10, 2))

    confidence_level = db.Column(db.Enum(ConfidenceLevel), nullable=False)
    confidence_score = db.Column(db.Float)  # 0..1, осмысленно только для llm_guess

    review_status = db.Column(db.Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False)
    reviewed_at = db.Column(db.DateTime)
    # Оператор вручную выбрал другую позицию вместо предложенной системой —
    # confidence_level при этом не меняется (описывает, как нашла система),
    # а этот флаг отражает, что решение принял человек.
    manually_edited = db.Column(db.Boolean, default=False, nullable=False)

    raw_match_data = db.Column(db.JSON)  # сырой ответ parts_supplier_client / llm_client

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    repair_order = db.relationship("RepairOrder", back_populates="part_matches")

    def __repr__(self):
        return f"<PartMatch {self.contract_article} -> {self.matched_article} ({self.confidence_level})>"
