from datetime import datetime

from app.extensions import db


class Product(db.Model):
    __tablename__ = "products"

    id = db.Column(db.Integer, primary_key=True)
    ozon_product_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    sku = db.Column(db.String(64), nullable=False, index=True)
    ozon_sku = db.Column(db.String(64), index=True)
    name = db.Column(db.String(512), nullable=False)
    category = db.Column(db.String(256))
    cost_price = db.Column(db.Numeric(10, 2))
    current_price = db.Column(db.Numeric(10, 2))
    units_sold_7d = db.Column(db.Integer)
    revenue_7d = db.Column(db.Numeric(12, 2))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    price_snapshots = db.relationship(
        "PriceSnapshot", back_populates="product", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Product {self.sku} {self.name!r}>"
