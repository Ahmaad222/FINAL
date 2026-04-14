"""
ZeinaGuard Pro - Wireless Intrusion Prevention System
Flask Backend - Detection Engine and API Server

Production-ready configuration with:
- Proper Socket.IO initialization
- Comprehensive logging
- Health monitoring
- CORS support
"""

import os
import sys
import logging
from datetime import timedelta
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

# Import extensions and initialization functions
from routes import register_blueprints
from websocket_server import init_socketio
from models import db, User

# =========================================================
# Logging Configuration
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger('zeinaguard')
logger.setLevel(logging.INFO)

# =========================================================
# Environment Setup
# =========================================================

load_dotenv()

# =========================================================
# Flask Application Factory
# =========================================================

def create_app(config_object=None):
    """
    Application factory for creating Flask app instances.

    Args:
        config_object: Optional configuration object to override defaults

    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)

    # --- Core Configuration ---
    app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change-me-in-production')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
    app.config['JSON_SORT_KEYS'] = False
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
        'DATABASE_URL',
        'postgresql://zeinaguard_user:secure_password_change_me@postgres:5432/zeinaguard_db'
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ECHO'] = os.getenv('SQLALCHEMY_ECHO', 'false').lower() == 'true'

    # --- CORS Configuration ---
    cors_origins = os.getenv('CORS_ORIGINS', '*')
    CORS(app, resources={r"/*": {"origins": cors_origins}}, supports_credentials=True)

    # --- Extensions Initialization ---
    db.init_app(app)
    JWTManager(app)

    # --- Database Setup ---
    with app.app_context():
        try:
            logger.info("[DB] Initializing database...")
            db.create_all()

            # Create or update admin user
            admin_user = User.query.filter_by(username='admin').first()

            if not admin_user:
                logger.info("[DB] Creating admin user...")
                new_admin = User(
                    username='admin',
                    email='admin@zeinaguard.local',
                    password_hash=generate_password_hash('admin123'),
                    is_admin=True,
                    is_active=True
                )
                db.session.add(new_admin)
                db.session.commit()
                logger.info("[DB] ✅ Admin user created")
            else:
                # Ensure admin is active
                admin_user.is_active = True
                admin_user.password_hash = generate_password_hash('admin123')
                db.session.commit()
                logger.info("[DB] 🔄 Admin user updated")

        except Exception as e:
            logger.error(f"[DB ERROR] Database initialization failed: {e}", exc_info=True)
            raise

    # --- Socket.IO Initialization ---
    logger.info("[SocketIO] Initializing...")
    socketio = init_socketio(app)
    app.socketio = socketio
    logger.info("[SocketIO] ✅ Initialized")

    # --- Register Blueprints ---
    register_blueprints(app)
    logger.info("[Blueprints] ✅ Registered")

    # --- Register Routes ---
    register_routes(app)

    return app


def register_routes(app):
    """Register additional application routes."""

    @app.route('/health', methods=['GET'])
    def health():
        """
        Health check endpoint.
        Returns: JSON with status 'healthy'
        """
        return jsonify({
            'status': 'healthy',
            'service': 'zeinaguard-backend',
            'version': '1.0.0'
        }), 200

    @app.route('/ready', methods=['GET'])
    def ready():
        """
        Readiness check endpoint.
        Verifies database and Socket.IO connectivity.
        """
        try:
            # Check database
            db.session.execute('SELECT 1')

            # Check Socket.IO
            socketio_ready = app.socketio is not None

            return jsonify({
                'ready': True,
                'database': 'connected',
                'socketio': 'initialized' if socketio_ready else 'not_initialized'
            }), 200

        except Exception as e:
            return jsonify({
                'ready': False,
                'error': str(e)
            }), 503

    @app.route('/', methods=['GET'])
    def root():
        """Root endpoint - API information."""
        return jsonify({
            'service': 'ZeinaGuard Backend',
            'version': '1.0.0',
            'description': 'Wireless Intrusion Prevention System API',
            'endpoints': {
                'health': '/health',
                'ready': '/ready',
                'api': '/api/*',
                'socketio': 'WebSocket connections on /socket.io/'
            }
        }), 200

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'error': 'Not Found',
            'message': str(error)
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({
            'error': 'Internal Server Error',
            'message': str(error)
        }), 500

    @app.errorhandler(Exception)
    def handle_exception(error):
        logger.error(f"[ERROR] Unhandled exception: {error}", exc_info=True)
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred'
        }), 500


# =========================================================
# Application Entry Point
# =========================================================

# Create application instance
app = create_app()


if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'

    logger.info(f"🚀 Starting ZeinaGuard Backend on port {port}")
    logger.info(f"   Debug mode: {debug}")
    logger.info(f"   Environment: {os.getenv('FLASK_ENV', 'development')}")

    # Run with Socket.IO server
    socketio = app.socketio
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=debug,
        allow_unsafe_werkzeug=True,
        use_reloader=debug
    )
