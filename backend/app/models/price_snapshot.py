import enum
from datetime import datetime

from app.extensions import db


class PriceSuggestionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PriceSnapshot(db.Model):
    """Снимок цен по товару: свои данные + рынок + предложение LLM.

    Автоприменение цены намеренно отключено — approve/reject человеком
    на фронте, пока не накоплена статистика точности модели.
    """

    __tablename__ = "price_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False, index=True)

    own_price = db.Column(db.Numeric(10, 2))
    own_position = db.Column(db.Integer)
    own_sales_last_7d = db.Column(db.Integer)

    competitor_min_price = db.Column(db.Numeric(10, 2))
    competitor_avg_price = db.Column(db.Numeric(10, 2))
    competitor_raw_data = db.Column(db.JSON)  # сырой ответ analytics_provider

    suggested_price = db.Column(db.Numeric(10, 2))
    suggestion_reasoning = db.Column(db.Text)  # объяснение LLM
    status = db.Column(
        db.Enum(PriceSuggestionStatus), default=PriceSuggestionStatus.PENDING, nullable=False
    )
    reviewed_at = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship("Product", back_populates="price_snapshots")

    def __repr__(self):
        return f"<PriceSnapshot product={self.product_id} status={self.status}>"
