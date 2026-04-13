"""
ZeinaGuard Pro - Wireless Intrusion Prevention System
Flask Backend - Detection Engine and API Server
"""

import os
import sys
import subprocess
import importlib.util

# --------------------------------
# 📦 Runtime Dependency Checker
# --------------------------------
BACKEND_DEPENDENCIES = {
    "Flask": "flask",
    "Flask-CORS": "flask_cors",
    "Flask-JWT-Extended": "flask_jwt_extended",
    "Flask-SQLAlchemy": "flask_sqlalchemy",
    "Flask-SocketIO": "flask_socketio",
    "python-dotenv": "dotenv",
    "redis": "redis",
    "psycopg2-binary": "psycopg2",
    "scapy": "scapy"
}

def ensure_dependencies():
    """Checks and installs missing backend dependencies at runtime."""
    for package, module in BACKEND_DEPENDENCIES.items():
        if importlib.util.find_spec(module) is None:
            print(f"Missing dependency: {package} → installing...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package], 
                                      stdout=subprocess.DEVNULL, 
                                      stderr=subprocess.STDOUT)
            except Exception as e:
                print(f"❌ Failed to install {package}: {e}")
                # We don't exit(1) here to allow the app to potentially run if the module 
                # name mapping was slightly off but the package is actually there.

ensure_dependencies()

from datetime import datetime, timedelta
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from auth import AuthService
from routes import register_blueprints
from websocket_server import init_socketio
from models import db

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# Configuration
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change-me-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.config['JSON_SORT_KEYS'] = False

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql://zeinaguard_user:secure_password_change_me@localhost:5432/zeinaguard_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
}

# Enable CORS - allow all origins for Replit proxy compatibility
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        "allow_headers": ['Content-Type', 'Authorization']
    }
})

# Initialize Database
db.init_app(app)

# --------------------------------
# 🛠️ DEBUG_RESET Logic (Part 3)
# --------------------------------
def debug_reset_db():
    with app.app_context():
        if os.getenv("DEBUG_RESET", "false").lower() == "true":
            print("[DEBUG] 🧹 DEBUG_RESET is true. Clearing DB tables...")
            try:
                # Clear specific tables to avoid full drop/create overhead
                db.session.execute(text("TRUNCATE TABLE threats CASCADE;"))
                db.session.execute(text("TRUNCATE TABLE network_topology CASCADE;"))
                db.session.execute(text("TRUNCATE TABLE sensor_health CASCADE;"))
                db.session.commit()
                print("[DEBUG] ✅ Database tables cleared.")
            except Exception as e:
                db.session.rollback()
                print(f"[DEBUG] ❌ Error resetting DB: {e}")

# Initialize JWT
auth_service = AuthService(app)

# Initialize WebSocket (Socket.io)
socketio = init_socketio(app)
app.socketio = socketio  # Store reference for broadcasting

# Register API blueprints
register_blueprints(app)

# Create tables and fix schema on startup
with app.app_context():
    try:
        from models import db
        db.create_all()
        print("[DB] Initial tables verified")
        
        # Apply schema fixes
        try:
            from fix_db_schema import fix_schema
            from sqlalchemy import text
            fix_schema()
            print("[DB] Basic schema fixes applied")
            
            # Apply TimescaleDB migration
            from migrate_timescale import migrate
            migrate()
            print("[DB] TimescaleDB migration applied successfully")
            
            # Run Debug Reset
            debug_reset_db()
            
        except ImportError as e:
            print(f"[DB] Warning: Migration script not found: {e}")
        except Exception as migration_error:
            print(f"[DB] Error during migration: {migration_error}")
            
    except Exception as e:
        print(f"[DB] Critical: Could not initialize database: {e}")

# Health check endpoint
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint for Docker healthcheck"""
    db_status = 'ok'
    try:
        from sqlalchemy import text
        db.session.execute(text("SELECT 1"))
    except Exception:
        db_status = 'error'
        
    return jsonify({
        'status': 'healthy' if db_status == 'ok' else 'degraded',
        'service': 'zeinaguard-backend',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat()
    }), 200 if db_status == 'ok' else 500

# Root endpoint
@app.route('/', methods=['GET'])
def root():
    """Root endpoint - API information"""
    return jsonify({
        'service': 'ZeinaGuard Pro Backend',
        'version': '1.0.0',
        'status': 'running',
        'environment': os.getenv('FLASK_ENV', 'development'),
        'endpoints': {
            'auth': '/api/auth/login',
            'threats': '/api/threats',
            'sensors': '/api/sensors',
            'alerts': '/api/alerts',
            'analytics': '/api/analytics',
            'users': '/api/users',
            'topology': '/api/topology'
        }
    }), 200

# API status endpoint
@app.route('/api/status', methods=['GET'])
def api_status():
    """API status endpoint"""
    return jsonify({
        'api': 'operational',
        'database': 'pending',
        'redis': 'pending',
        'detection_engine': 'initializing',
        'version': '1.0.0'
    }), 200

# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found', 'code': 404}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error', 'code': 500}), 500

if __name__ == '__main__':
    # Development server with WebSocket support
    port = int(os.getenv('FLASK_PORT', 8000))
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true',
        allow_unsafe_werkzeug=True
    )
