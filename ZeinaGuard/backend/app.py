"""
ZeinaGuard Pro - Wireless Intrusion Prevention System
Flask Backend - Detection Engine and API Server
"""

import os
import sys
import subprocess
import importlib.util
from datetime import timedelta
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from auth import AuthService
from routes import register_blueprints
from websocket_server import init_socketio
from models import db, User

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
    for package, module in BACKEND_DEPENDENCIES.items():
        if importlib.util.find_spec(module) is None:
            print(f"Missing dependency: {package} → installing...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package],
                                      stdout=subprocess.DEVNULL,
                                      stderr=subprocess.STDOUT)
            except Exception as e:
                print(f"❌ Failed to install {package}: {e}")

ensure_dependencies()

# Load environment variables
load_dotenv()

app = Flask(__name__)

# --- Configuration ---
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'change-me-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=24)
app.config['JSON_SORT_KEYS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL',
    'postgresql://zeinaguard_user:secure_password_change_me@postgres:5432/zeinaguard_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- CORS ---
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- Extensions ---
db.init_app(app)
auth_service = AuthService(app)
socketio = init_socketio(app)
app.socketio = socketio

register_blueprints(app)

# --------------------------------
# 🛡️ Setup DB AFTER START
# --------------------------------
def setup_initial_data():
    with app.app_context():
        try:
            db.create_all()

            admin_user = User.query.filter_by(username='admin').first()

            if not admin_user:
                print("[DB] 🆕 Creating admin...")
                new_admin = User(
                    username='admin',
                    email='admin@zeinaguard.local',
                    password_hash=generate_password_hash('admin123'),
                    is_admin=True,
                    is_active=True
                )
                db.session.add(new_admin)
                db.session.commit()
                print("[DB] ✅ Admin created")
            else:
                admin_user.password_hash = generate_password_hash('admin123')
                admin_user.is_active = True
                db.session.commit()
                print("[DB] 🔄 Admin updated")

        except Exception as e:
            print(f"[DB ERROR] {e}")

# --------------------------------
# 🔥 Run setup AFTER first request
# --------------------------------
@app.before_first_request
def initialize():
    print("[INIT] Running DB setup...")
    setup_initial_data()

# --------------------------------
# Routes
# --------------------------------
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'}), 200

@app.route('/', methods=['GET'])
def root():
    return jsonify({'service': 'ZeinaGuard Backend'}), 200

# --------------------------------
# Run
# --------------------------------
if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)