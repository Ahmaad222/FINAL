"""
ZeinaGuard Flask backend entrypoint.

Container goals:
- start reliably under Gunicorn
- tolerate brief PostgreSQL warmup
- expose lightweight liveness and readiness checks
- log startup milestones for Docker debugging
"""

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
from websocket_server import init_socketio


logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger('zeinaguard')
logger.setLevel(logging.INFO)

load_dotenv()

DB_CONNECT_RETRIES = int(os.getenv('DB_CONNECT_RETRIES', '15'))
DB_CONNECT_DELAY_SECONDS = float(os.getenv('DB_CONNECT_DELAY_SECONDS', '2'))


def initialize_database():
    """Wait for PostgreSQL, create tables, and bootstrap the default admin."""
    logger.info('[DB] Waiting for PostgreSQL to accept connections')

    last_error = None
    for attempt in range(1, DB_CONNECT_RETRIES + 1):
        try:
            db.session.execute(text('SELECT 1'))
            db.create_all()

            admin_user = User.query.filter_by(username='admin').first()
            if not admin_user:
                logger.info('[DB] Creating default admin user')
                admin_user = User(
                    username='admin',
                    email='admin@zeinaguard.local',
                    password_hash=generate_password_hash('admin123'),
                    is_admin=True,
                    is_active=True,
                )
                db.session.add(admin_user)
            else:
                admin_user.is_active = True
                admin_user.password_hash = generate_password_hash('admin123')

            db.session.commit()
            logger.info('[DB] Database connection verified and bootstrap completed')
            return
        except OperationalError as exc:
            last_error = exc
            db.session.rollback()
            logger.warning(
                '[DB] Connection attempt %s/%s failed: %s',
                attempt,
                DB_CONNECT_RETRIES,
                exc,
            )
            if attempt < DB_CONNECT_RETRIES:
                time.sleep(DB_CONNECT_DELAY_SECONDS)
        except Exception:
            db.session.rollback()
            logger.exception('[DB] Database initialization failed')
            raise

    logger.error('[DB] PostgreSQL did not become ready after %s attempts', DB_CONNECT_RETRIES)
    raise last_error or RuntimeError('Database initialization failed')


def register_routes(app):
    @app.route('/health', methods=['GET'])
    def health():
        return jsonify(
            {
                'status': 'healthy',
                'service': 'zeinaguard-backend',
                'socketio': 'initialized' if getattr(app, 'socketio', None) else 'not_initialized',
            }
        ), 200

    @app.route('/ready', methods=['GET'])
    def ready():
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify(
                {
                    'ready': True,
                    'database': 'connected',
                    'socketio': 'initialized' if getattr(app, 'socketio', None) else 'not_initialized',
                }
            ), 200
        except Exception as exc:
            logger.warning('[Ready] Readiness check failed: %s', exc)
            return jsonify({'ready': False, 'error': str(exc)}), 503

    @app.route('/', methods=['GET'])
    def root():
        return jsonify(
            {
                'service': 'ZeinaGuard Backend',
                'version': '1.0.0',
                'description': 'Wireless Intrusion Prevention System API',
                'endpoints': {
                    'health': '/health',
                    'ready': '/ready',
                    'api': '/api/*',
                    'socketio': '/socket.io/',
                },
            }
        ), 200

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not Found', 'message': str(error)}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal Server Error', 'message': str(error)}), 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        if isinstance(error, HTTPException):
            return jsonify({'error': error.name, 'message': error.description}), error.code

        logger.exception('[App] Unhandled exception')
        return jsonify({'error': 'Internal Server Error', 'message': 'An unexpected error occurred'}), 500


def create_app(config_object=None):
    app = Flask(__name__)

    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change-me-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
    app.config['JSON_SORT_KEYS'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL',
        'postgresql://zeinaguard_user:secure_password_change_me@postgres:5432/zeinaguard_db',
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ECHO'] = os.getenv('SQLALCHEMY_ECHO', 'false').lower() == 'true'

    if config_object:
        app.config.from_object(config_object)

    cors_origins = os.getenv('CORS_ORIGINS', '*')
    CORS(app, resources={r'/*': {'origins': cors_origins}}, supports_credentials=True)

    db.init_app(app)
    JWTManager(app)

    with app.app_context():
        initialize_database()

    logger.info('[SocketIO] Initializing Socket.IO server')
    app.socketio = init_socketio(app)
    logger.info('[SocketIO] Socket.IO initialized successfully')

    register_blueprints(app)
    logger.info('[App] Blueprints registered successfully')

    register_routes(app)
    logger.info('[App] Application startup completed successfully')

    return app


app = create_app()


if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'

    logger.info('[App] Starting ZeinaGuard Backend on port %s', port)
    logger.info('[App] Debug mode: %s', debug)
    logger.info('[App] Environment: %s', os.getenv('FLASK_ENV', 'development'))

    app.socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
        use_reloader=debug,
    )
