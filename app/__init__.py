import os

from flask import Flask, render_template
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from config import config_by_name

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app(config_name=None):
    config_name = config_name or os.environ.get("FLASK_ENV", "production")
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name[config_name])

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "strong"

    from app.models import Stakeholder

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Stakeholder, int(user_id))

    from app.auth import auth_bp
    from app.main import main_bp
    from app.notion_import import notion_import_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(notion_import_bp)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; font-src 'self'; "
            "img-src 'self' data:; script-src 'self'"
        )
        return response

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/error.html", code=403, message="You don't have access to that page."), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/error.html", code=404, message="That page doesn't exist."), 404

    @app.errorhandler(413)
    def too_large(e):
        return render_template("errors/error.html", code=413, message="That file is too large (10 MB limit)."), 413

    @app.cli.command("seed-admin")
    def seed_admin():
        """Create the first Program Director account from env vars, or interactively."""
        from app.seed import seed_admin as _seed_admin

        _seed_admin()

    @app.cli.command("init-db")
    def init_db():
        """Create all tables. Safe to run repeatedly (no-op on existing tables)."""
        with app.app_context():
            db.create_all()
        print("Database tables ensured.")

    @app.cli.command("notion-sync")
    def notion_sync():
        """Pull the latest Stakeholder/Project/Topic data from Notion.

        Reads NOTION_TOKEN from the environment (local .env only -- never
        committed, never read by the web app itself). Meant to be run on a
        schedule (see README's "Local network hosting" section).
        """
        from pathlib import Path

        from app.notion_sync import run_notion_sync, write_report

        with app.app_context():
            report = run_notion_sync(Path(app.root_path).parent)
            path = write_report(report, Path(app.root_path).parent / "reports")
        print(f"Notion sync done. Report: {path}")
        if report.new_credentials:
            print(f"{len(report.new_credentials)} new account(s) created -- see the report for passwords.")
        if report.needs_attention:
            print(f"{len(report.needs_attention)} item(s) need attention -- see the report.")

    return app
