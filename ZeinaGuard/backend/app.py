"""
ZeinaGuard Flask backend entrypoint.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from models import User, db
from routes import register_blueprints
from schema_migration import apply_runtime_migrations
from websocket_server import init_socketio


def configure_logging() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    logging.getLogger("engineio").setLevel(logging.ERROR)
    logging.getLogger("socketio").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.ERROR)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.ERROR)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    app_logger = logging.getLogger("zeinaguard")
    app_logger.setLevel(logging.INFO)
    return app_logger


logger = configure_logging()

load_dotenv()

DB_CONNECT_RETRIES = int(os.getenv("DB_CONNECT_RETRIES", "15"))
DB_CONNECT_DELAY_SECONDS = float(os.getenv("DB_CONNECT_DELAY_SECONDS", "2"))


def initialize_database():
    logger.info("[DB] Waiting for PostgreSQL to accept connections")

    last_error = None
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            db.session.execute(text("SELECT 1"))
            db.create_all()
            apply_runtime_migrations()

            admin_user = User.query.filter_by(username="admin").first()
            if not admin_user:
                admin_user = User(
                    username="admin",
                    email="admin@zeinaguard.local",
                    password_hash=generate_password_hash("admin123"),
                    is_admin=True,
                    is_active=True,
                )
                db.session.add(admin_user)
            else:
                admin_user.is_active = True
                admin_user.password_hash = generate_password_hash("admin123")

            db.session.commit()
            logger.info("[DB] Database connection verified")
            return
        except OperationalError as exc:
            last_error = exc
            db.session.rollback()
            logger.warning("[DB] Connection attempt %s/%s failed: %s", attempt, DB_CONNECT_RETRIES, exc)
            if attempt < DB_CONNECT_RETRIES:
                time.sleep(DB_CONNECT_DELAY_SECONDS)
        except Exception:
            db.session.rollback()
            logger.exception("[DB] Database initialization failed")
            raise

    raise last_error or RuntimeError("Database initialization failed")


def register_routes(app):
    @app.route("/health", methods=["GET"])
    def health():
        return jsonify(
            {
                "status": "healthy",
                "service": "zeinaguard-backend",
                "socketio": "initialized" if getattr(app, "socketio", None) else "not_initialized",
            }
        ), 200

    @app.route("/ready", methods=["GET"])
    def ready():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify({"ready": True, "database": "connected"}), 200
        except Exception as exc:
            logger.warning("[DB] Readiness check failed: %s", exc)
            return jsonify({"ready": False, "error": str(exc)}), 503

    @app.route("/", methods=["GET"])
    def root():
        return jsonify(
            {
                "service": "ZeinaGuard Backend",
                "version": "1.0.0",
                "description": "Wireless Intrusion Prevention System API",
            }
        ), 200

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not Found", "message": str(error)}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal Server Error", "message": str(error)}), 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        if isinstance(error, HTTPException):
            return jsonify({"error": error.name, "message": error.description}), error.code
        logger.exception("[App] Unhandled exception")
        return jsonify({"error": "Internal Server Error", "message": "An unexpected error occurred"}), 500


def create_app(config_object=None):
    app = Flask(__name__)

    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=24)
    app.config["JSON_SORT_KEYS"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "postgresql://zeinaguard_user:secure_password_change_me@postgres:5432/zeinaguard_db",
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ECHO"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800")),
        "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("DB_POOL_MAX_OVERFLOW", "30")),
        "pool_timeout": int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30")),
    }

    if config_object:
        app.config.from_object(config_object)

    CORS(app, resources={r"/*": {"origins": os.getenv("CORS_ORIGINS", "*")}}, supports_credentials=True)

    db.init_app(app)
    JWTManager(app)

    with app.app_context():
        initialize_database()

    app.socketio = init_socketio(app)
    register_blueprints(app)
    register_routes(app)
    logger.info("[App] Startup completed")

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.socketio.run(
        app,
        host="0.0.0.0",
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
        use_reloader=debug,
    )
