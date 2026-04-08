"""
JWT Authentication Module for ZeinaGuard Pro
Handles user authentication, token generation, and validation using SQLAlchemy models
"""

from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask import request, jsonify, Blueprint
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, 
    get_jwt_identity, get_jwt
)
from models import db, User
import os

# Password hashing configuration
HASH_METHOD = 'pbkdf2:sha256'

# Define Blueprint for Auth routes
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256"""
    return generate_password_hash(password, method=HASH_METHOD)

def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify a password against its hash"""
    return check_password_hash(stored_hash, provided_password)

def authenticate_user(username: str, password: str):
    """
    Authenticate user by username and password using the database
    Returns user object if valid, None otherwise
    """
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return None
    
    if not user.is_active:
        return None
    
    if not verify_password(user.password_hash, password):
        return None
    
    return user

def get_user_by_id(user_id: int):
    """Get user by ID from the database"""
    return User.query.get(user_id)

class AuthService:
    """Service for handling authentication operations"""
    
    def __init__(self, app=None):
        self.app = app
        self.jwt = None
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize JWT with Flask app"""
        self.jwt = JWTManager(app)
        
        # JWT error handlers
        @self.jwt.expired_token_loader
        def expired_token_callback(jwt_header, jwt_data):
            return jsonify({
                'error': 'Token has expired',
                'code': 'token_expired'
            }), 401
        
        @self.jwt.invalid_token_loader
        def invalid_token_callback(error):
            return jsonify({
                'error': 'Invalid token',
                'code': 'invalid_token'
            }), 401
        
        @self.jwt.unauthorized_loader
        def missing_token_callback(error):
            return jsonify({
                'error': 'Request does not contain an access token',
                'code': 'authorization_required'
            }), 401
    
    @staticmethod
    def create_tokens(user_id: int, username: str, email: str, is_admin: bool = False):
        """Create JWT access token and return user info"""
        identity = {
            'user_id': user_id,
            'username': username,
            'email': email,
            'is_admin': is_admin
        }
        
        access_token = create_access_token(
            identity=identity,
            expires_delta=timedelta(hours=24)
        )
        
        return {
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': 86400,
            'user': {
                'id': user_id,
                'username': username,
                'email': email,
                'is_admin': is_admin
            }
        }

def token_required(f):
    """Decorator to require JWT token"""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        current_user = get_jwt_identity()
        return f(current_user, *args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        current_user = get_jwt_identity()
        if not current_user.get('is_admin'):
            return jsonify({'error': 'Admin access required'}), 403
        return f(current_user, *args, **kwargs)
    return decorated_function

# --- Auth Routes ---

@auth_bp.route('/login', methods=['POST'])
def login():
    """User login endpoint"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON'}), 400
            
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Missing username or password'}), 400
            
        user = authenticate_user(username, password)
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
            
        return jsonify(AuthService.create_tokens(
            user_id=user.id,
            username=user.username,
            email=user.email,
            is_admin=user.is_admin
        )), 200
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_me():
    """Get current authenticated user information"""
    return jsonify(get_jwt_identity()), 200

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout endpoint"""
    return jsonify({'message': 'Logged out successfully'}), 200
