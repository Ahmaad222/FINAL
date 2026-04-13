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
from werkzeug.security import generate_password_hash # لإضافة التشفير الصحيح

# استيراد الملفات المحلية
from auth import AuthService
from routes import register_blueprints
from websocket_server import init_socketio
from models import db, User  # استيراد User لإنشاء الأدمن

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

# --- CORS Setup ---
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- Initialize Extensions ---
db.init_app(app)
auth_service = AuthService(app)
socketio = init_socketio(app)
app.socketio = socketio 

register_blueprints(app)

# --------------------------------
# 🛡️ Automatic Admin Creation
# --------------------------------
def setup_initial_data():
    with app.app_context():
        try:
            db.create_all()
            # التحقق من وجود الأدمن أو تحديث باسورده
            admin_user = User.query.filter_by(username='admin').first()
            
            if not admin_user:
                print("[DB] 🆕 Admin not found. Creating default admin...")
                new_admin = User(
                    username='admin',
                    email='admin@zeinaguard.local',
                    password_hash=generate_password_hash('admin123'),
                    is_admin=True,
                    is_active=True
                )
                db.session.add(new_admin)
                db.session.commit()
                print("[DB] ✅ Default admin created (admin/admin123)")
            else:
                # تحديث الـ Hash لضمان التوافق مع المكتبة الحالية
                admin_user.password_hash = generate_password_hash('admin123')
                admin_user.is_active = True
                db.session.commit()
                print("[DB] 🔄 Admin account verified and password hash updated.")
                
        except Exception as e:
            print(f"[DB] Error during startup: {e}")

# تنفيذ التهيئة
setup_initial_data()

# --- Routes ---
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'service': 'zeinaguard-backend'}), 200

@app.route('/', methods=['GET'])
def root():
    return jsonify({'service': 'ZeinaGuard Pro Backend', 'status': 'running'}), 200

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)