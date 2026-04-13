"""
JWT Authentication Module for ZeinaGuard Pro
"""
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask import request, jsonify, Blueprint
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from models import db, User

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

def verify_password(stored_hash: str, provided_password: str) -> bool:
    if not stored_hash or not provided_password:
        return False
    return check_password_hash(stored_hash, provided_password)

def authenticate_user(username: str, password: str):
    user = User.query.filter_by(username=username).first()
    
    if not user:
        print(f"[AUTH] ❌ User not found: {username}")
        return None
    
    if not user.is_active:
        print(f"[AUTH] ❌ User inactive: {username}")
        return None
    
    if not verify_password(user.password_hash, password):
        print(f"[AUTH] ❌ Password mismatch for user: {username}")
        return None
    
    print(f"[AUTH] ✅ User authenticated: {username}")
    return user

# ... (بقية كود AuthService و Create Tokens كما هي لديك) ...

@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        user = authenticate_user(username, password)
        if not user:
            # نرجع خطأ موحد للأمان، لكننا طبعنا السبب في السيرفر فوق
            return jsonify({'error': 'Invalid credentials'}), 401
            
        return jsonify(AuthService.create_tokens(
            user_id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin
        )), 200
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}'}), 500