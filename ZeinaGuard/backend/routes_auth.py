"""
Auth API Routes for ZeinaGuard Pro
Provides database-backed authentication and user management
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from auth import AuthService, authenticate_user, get_user_by_id

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
users_bp = Blueprint('users', __name__, url_prefix='/api/users')
auth_service = AuthService()


@auth_bp.route('/login', methods=['POST'])
def login():
    """User login endpoint"""
    try:
        data = request.get_json()
        if not data or not data.get('username') or not data.get('password'):
            return jsonify({'error': 'Missing username or password'}), 400
            
        user = authenticate_user(data['username'], data['password'])
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
            
        tokens = auth_service.create_tokens(
            user_id=user['user_id'],
            username=user['username'],
            email=user['email'],
            is_admin=user.get('is_admin', False)
        )
        
        return jsonify(tokens), 200
    except Exception as e:
        return jsonify({'error': f'Login failed: {str(e)}'}), 500


@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """User logout endpoint"""
    return jsonify({'message': 'Logged out successfully'}), 200


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required()
def refresh():
    """Refresh access token"""
    try:
        current_user = get_jwt_identity()
        user = get_user_by_id(current_user['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        tokens = auth_service.create_tokens(
            user_id=user['user_id'],
            username=user['username'],
            email=user['email'],
            is_admin=user.get('is_admin', False)
        )
        return jsonify(tokens), 200
    except Exception as e:
        return jsonify({'error': f'Refresh failed: {str(e)}'}), 500


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current user info from token"""
    return jsonify(get_jwt_identity()), 200


@users_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_user_profile():
    """Get detailed user profile from database"""
    try:
        current_user = get_jwt_identity()
        user = get_user_by_id(current_user['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 404
            
        return jsonify(user), 200
    except Exception as e:
        return jsonify({'error': f'Profile fetch failed: {str(e)}'}), 500
