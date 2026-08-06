import os

from flask import Flask, jsonify, request, send_from_directory

from app.config import Config
from app.extensions import db, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db, directory=app.config.get("MIGRATIONS_DIR") or "migrations")

    from app.api.auth import bp as auth_bp
    from app.api.ozon.pricing import bp as ozon_pricing_bp
    from app.api.ozon.cards import bp as ozon_cards_bp
    from app.api.repair_orders.upload import bp as repair_upload_bp
    from app.api.repair_orders.matching import bp as repair_matching_bp
    from app.api.dashboard import bp as dashboard_bp
    from app.api.llm import bp as llm_bp
    from app.api.history import bp as history_bp
    from app.api.integrations import bp as integrations_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(ozon_pricing_bp, url_prefix="/api/ozon/pricing")
    app.register_blueprint(ozon_cards_bp, url_prefix="/api/ozon/cards")
    app.register_blueprint(repair_upload_bp, url_prefix="/api/repair-orders/upload")
    app.register_blueprint(repair_matching_bp, url_prefix="/api/repair-orders/matching")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(llm_bp, url_prefix="/api/llm")
    app.register_blueprint(history_bp, url_prefix="/api/history")
    app.register_blueprint(integrations_bp, url_prefix="/api/integrations")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.after_request
    def _no_store_api_responses(response):
        # Ответы Flask по умолчанию не несут Cache-Control — WebKitGTK (окно
        # native-режима) в таком случае агрессивно кэширует GET-запросы даже
        # через полный reload страницы. На практике это било по
        # /api/auth/setup-required: администратор проходил мастер /setup,
        # но при повторной загрузке окно показывало устаревший ответ
        # "setup_required: true" и снова предлагало создать администратора.
        # API-ответы не должны кэшироваться браузером/webview вообще —
        # актуальность данных важнее лишнего запроса.
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    _register_frontend_static_routes(app)

    # модели должны быть импортированы до Alembic autogenerate
    from app.models import product, price_snapshot, repair_order, part_match, contract, user, llm_setting, history, integration_setting  # noqa: F401

    register_cli(app)

    return app


def _register_frontend_static_routes(app):
    """Этот же Flask-процесс отдаёт собранный frontend/dist как статику —
    отдельного nginx/дев-сервера нет, единственная точка входа — окно
    pywebview (см. native_app.py)."""
    frontend_dist = app.config["FRONTEND_DIST_DIR"]

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_frontend(path):
        target = os.path.join(frontend_dist, path)
        if path and os.path.isfile(target):
            return send_from_directory(frontend_dist, path)
        # SPA-роутинг: любой не-статический путь отдаёт index.html,
        # react-router разбирается с ним уже на клиенте.
        return send_from_directory(frontend_dist, "index.html")


def register_cli(app):
    import click

    @app.cli.group("users")
    def users_group():
        """Управление пользователями AutoSync."""

    @users_group.command("create-admin")
    @click.option("--email", required=True)
    @click.option("--password", required=True)
    def create_admin(email, password):
        """Создать первого администратора: flask users create-admin --email ... --password ..."""
        from app.extensions import db
        from app.models import User, UserRole

        email = email.strip().lower()
        if User.query.filter_by(email=email).first():
            click.echo(f"Пользователь {email} уже существует.")
            return
        user = User(email=email, role=UserRole.ADMIN)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Администратор {email} создан.")
