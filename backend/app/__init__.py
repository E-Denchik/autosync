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
    from app.api.ozon.stats import bp as ozon_stats_bp
    from app.api.repair_orders.upload import bp as repair_upload_bp
    from app.api.repair_orders.matching import bp as repair_matching_bp
    from app.api.repair_orders.labor import bp as repair_labor_bp
    from app.api.dashboard import bp as dashboard_bp
    from app.api.llm import bp as llm_bp
    from app.api.history import bp as history_bp
    from app.api.integrations import bp as integrations_bp
    from app.api.contragents import bp as contragents_bp
    from app.api.labor_catalog import bp as labor_catalog_bp
    from app.api.nomenclature import bp as nomenclature_bp
    from app.api.company_profile import bp as company_profile_bp
    from app.api.document_templates import bp as document_templates_bp
    from app.api.file_preview import bp as file_preview_bp
    from app.api.contracts import bp as contracts_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(ozon_pricing_bp, url_prefix="/api/ozon/pricing")
    app.register_blueprint(ozon_cards_bp, url_prefix="/api/ozon/cards")
    app.register_blueprint(ozon_stats_bp, url_prefix="/api/ozon/stats")
    app.register_blueprint(repair_upload_bp, url_prefix="/api/repair-orders/upload")
    app.register_blueprint(repair_matching_bp, url_prefix="/api/repair-orders/matching")
    app.register_blueprint(repair_labor_bp, url_prefix="/api/repair-orders/labor")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(llm_bp, url_prefix="/api/llm")
    app.register_blueprint(history_bp, url_prefix="/api/history")
    app.register_blueprint(integrations_bp, url_prefix="/api/integrations")
    app.register_blueprint(contragents_bp, url_prefix="/api/contragents")
    app.register_blueprint(labor_catalog_bp, url_prefix="/api/labor-catalog")
    app.register_blueprint(nomenclature_bp, url_prefix="/api/nomenclature")
    app.register_blueprint(company_profile_bp, url_prefix="/api/company-profile")
    app.register_blueprint(document_templates_bp, url_prefix="/api/document-templates")
    app.register_blueprint(file_preview_bp, url_prefix="/api/file-preview")
    app.register_blueprint(contracts_bp, url_prefix="/api/contracts")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.before_request
    def _require_local_session_token():
        if app.config.get("TESTING") or request.path == "/api/health":
            return None
        token = app.config.get("SESSION_TOKEN")
        supplied = request.args.get("token") or request.cookies.get("autosync_token")
        if not token or supplied != token:
            return jsonify(error="AutoSync доступен только через собственное окно приложения"), 403
        return None

    @app.after_request
    def _persist_local_session_cookie(response):
        # Токен приходит в URL только на самой первой навигации (см.
        # native_app.py: main()) — дальше все запросы фронтенда (fetch к
        # /api/..., подгрузка статики) идут без query-параметра, поэтому
        # закрепляем токен в cookie сразу после первого успешного запроса.
        token = app.config.get("SESSION_TOKEN")
        if token and request.args.get("token") == token:
            response.set_cookie("autosync_token", token, httponly=True, samesite="Strict")
        return response

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
    from app.models import product, price_snapshot, repair_order, part_match, contract, contragent, labor_catalog, labor_line, nomenclature, user, llm_setting, history, integration_setting, document_template  # noqa: F401

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
    def create_admin(email):
        """Создать первого администратора: flask users create-admin --email ..."""
        from app.extensions import db
        from app.models import User, UserRole

        email = email.strip().lower()
        if User.query.filter_by(email=email).first():
            click.echo(f"Пользователь {email} уже существует.")
            return
        user = User(email=email, role=UserRole.ADMIN)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Администратор {email} создан.")
