"""
JWT Authentication Module for ZeinaGuard Pro
Handles user authentication, token generation, and validation
"""

from functools import wraps
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from flask import request, jsonify
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, 
    get_jwt_identity, get_jwt
)
import os

# Password hashing configuration
HASH_METHOD = 'pbkdf2:sha256'


def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256"""
    return generate_password_hash(password, method=HASH_METHOD)


def verify_password(stored_hash: str, provided_password: str) -> bool:
    """Verify a password against its hash"""
    return check_password_hash(stored_hash, provided_password)


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
        """
        Create JWT access token
        
        Args:
            user_id: User's database ID
            username: User's username
            email: User's email
            is_admin: Whether user is admin
        
        Returns:
            Dictionary with access token and expiration
        """
        identity = {
            'user_id': user_id,
            'username': username,
            'email': email,
            'is_admin': is_admin
        }
        
        access_token = create_access_token(
            identity=identity,
            expires_delta=timedelta(hours=24)  # 24 hour token lifetime
        )
        
        return {
            'access_token': access_token,
            'token_type': 'Bearer',
            'expires_in': 86400,  # 24 hours in seconds
            'user': {
                'id': user_id,
                'username': username,
                'email': email,
                'is_admin': is_admin
            }
        }
    
    @staticmethod
    def get_current_user():
        """Get current authenticated user from JWT"""
        try:
            identity = get_jwt_identity()
            return identity
        except:
            return None
    
    @staticmethod
    def get_current_user_id():
        """Get current user ID from JWT"""
        identity = get_jwt_identity()
        if identity:
            return identity.get('user_id')
        return None


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


def authenticate_user(username: str, password: str):
    """
    Authenticate user by username and password
    Returns user data if valid, None otherwise
    """
    from models import User
    user = User.query.filter_by(username=username).first()
    
    if not user:
        return None
    
    if not user.is_active:
        return None
    
    if not verify_password(user.password_hash, password):
        return None
    
    return {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'is_admin': user.is_admin,
        'is_active': user.is_active
    }


def get_user_by_id(user_id: int):
    """Get user by ID"""
    from models import User
    user = User.query.get(user_id)
    if not user:
        return None
        
    return {
        'user_id': user.id,
        'username': user.username,
        'email': user.email,
        'is_admin': user.is_admin,
        'is_active': user.is_active
    }
