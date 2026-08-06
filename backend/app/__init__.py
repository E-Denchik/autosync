from flask import Flask, jsonify
from flask_cors import CORS

from app.config import Config
from app.extensions import db, migrate, celery


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)
    CORS(app)

    configure_celery(app)

    from app.api.ozon.pricing import bp as ozon_pricing_bp
    from app.api.ozon.cards import bp as ozon_cards_bp
    from app.api.repair_orders.upload import bp as repair_upload_bp
    from app.api.repair_orders.matching import bp as repair_matching_bp
    from app.api.dashboard import bp as dashboard_bp

    app.register_blueprint(ozon_pricing_bp, url_prefix="/api/ozon/pricing")
    app.register_blueprint(ozon_cards_bp, url_prefix="/api/ozon/cards")
    app.register_blueprint(repair_upload_bp, url_prefix="/api/repair-orders/upload")
    app.register_blueprint(repair_matching_bp, url_prefix="/api/repair-orders/matching")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    # модели должны быть импортированы до Alembic autogenerate
    from app.models import product, price_snapshot, repair_order, part_match, contract  # noqa: F401

    return app


def configure_celery(app):
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
    )

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery
