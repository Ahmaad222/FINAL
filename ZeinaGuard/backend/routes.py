"""
API Routes for ZeinaGuard Pro Backend
Handles authentication, threats, sensors, and other endpoints
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from auth import (
    AuthService, authenticate_user, token_required, 
    admin_required, get_user_by_id
)
from websocket_server import broadcast_threat_event, broadcast_sensor_status

# Create blueprints
auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')
threats_bp = Blueprint('threats', __name__, url_prefix='/api/threats')
sensors_bp = Blueprint('sensors', __name__, url_prefix='/api/sensors')
alerts_bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')
analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')
users_bp = Blueprint('users', __name__, url_prefix='/api/users')

# Initialize auth service
auth_service = AuthService()


# ==================== Authentication Routes ====================

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    User login endpoint
    Expected JSON: { "username": "...", "password": "..." }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'Missing request body'}), 400
        
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Missing username or password'}), 400
        
        # Authenticate user
        user = authenticate_user(username, password)
        
        if not user:
            return jsonify({'error': 'Invalid credentials'}), 401
        
        # Create tokens
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
    """
    User logout endpoint
    Token revocation would be implemented with database in production
    """
    return jsonify({'message': 'Logged out successfully'}), 200


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required()
def refresh():
    """
    Refresh access token
    Requires valid JWT token
    """
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
        return jsonify({'error': f'Token refresh failed: {str(e)}'}), 500


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current authenticated user information"""
    try:
        current_user = get_jwt_identity()
        return jsonify(current_user), 200
    except Exception as e:
        return jsonify({'error': f'Failed to get user: {str(e)}'}), 500


# ==================== Threat Routes ====================

@threats_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_threats():
    """Get list of threats with optional filtering"""
    try:
        # Query parameters
        limit = request.args.get('limit', default=50, type=int)
        offset = request.args.get('offset', default=0, type=int)
        severity = request.args.get('severity', default=None, type=str)
        is_resolved = request.args.get('resolved', default=None, type=bool)
        
        # Mock threat data (will come from database in Phase 3)
        mock_threats = [
            {
                'id': 1,
                'threat_type': 'rogue_ap',
                'severity': 'critical',
                'source_mac': '00:11:22:33:44:55',
                'ssid': 'FreeWiFi',
                'detected_by': 1,
                'description': 'Rogue access point detected in office area',
                'is_resolved': False,
                'created_at': datetime.now().isoformat()
            },
            {
                'id': 2,
                'threat_type': 'deauth_attack',
                'severity': 'high',
                'source_mac': 'AA:BB:CC:DD:EE:FF',
                'target_mac': '11:22:33:44:55:66',
                'detected_by': 2,
                'description': 'Deauthentication attack detected',
                'is_resolved': False,
                'created_at': datetime.now().isoformat()
            }
        ]
        
        # Filter by severity
        if severity:
            mock_threats = [t for t in mock_threats if t['severity'] == severity]
        
        # Filter by resolved status
        if is_resolved is not None:
            mock_threats = [t for t in mock_threats if t['is_resolved'] == is_resolved]
        
        # Apply pagination
        total = len(mock_threats)
        threats = mock_threats[offset:offset + limit]
        
        return jsonify({
            'data': threats,
            'pagination': {
                'total': total,
                'limit': limit,
                'offset': offset
            }
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch threats: {str(e)}'}), 500


@threats_bp.route('/<int:threat_id>', methods=['GET'])
@jwt_required(optional=True)
def get_threat(threat_id):
    """Get threat details"""
    try:
        threat = {
            'id': threat_id,
            'threat_type': 'rogue_ap',
            'severity': 'critical',
            'source_mac': '00:11:22:33:44:55',
            'ssid': 'FreeWiFi',
            'detected_by': 1,
            'description': 'Rogue access point detected in office area',
            'is_resolved': False,
            'created_at': datetime.now().isoformat(),
            'events': [
                {
                    'id': 1,
                    'timestamp': datetime.now().isoformat(),
                    'signal_strength': -45,
                    'packet_count': 150
                }
            ]
        }
        return jsonify(threat), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch threat: {str(e)}'}), 500


@threats_bp.route('/<int:threat_id>/resolve', methods=['POST'])
@jwt_required(optional=True)
def resolve_threat(threat_id):
    """Mark threat as resolved"""
    try:
        current_user = get_jwt_identity() or {}
        
        return jsonify({
            'message': 'Threat resolved successfully',
            'threat_id': threat_id,
            'resolved_by': current_user.get('username', 'anonymous'),
            'resolved_at': datetime.now().isoformat()
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to resolve threat: {str(e)}'}), 500


@threats_bp.route('/<int:threat_id>/block', methods=['POST'])
@jwt_required(optional=True)
def block_threat(threat_id):
    """Block/whitelist a threat"""
    try:
        data = request.get_json()
        action = data.get('action', 'block') if data else 'block'
        
        return jsonify({
            'message': 'Threat blocked/whitelisted',
            'threat_id': threat_id,
            'action': action,
            'blocked_at': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to block threat: {str(e)}'}), 500


@threats_bp.route('/demo/simulate-threat', methods=['POST'])
@jwt_required(optional=True)
def simulate_threat():
    """
    Demo endpoint to simulate a real-time threat detection
    Broadcasts threat event via WebSocket to all connected clients
    This simulates what would happen when the detection engine finds a threat
    """
    try:
        current_user = get_jwt_identity() or {}
        
        # Simulate threat data
        threat_data = {
            'id': 1,
            'threat_type': 'rogue_ap',
            'severity': 'critical',
            'source_mac': '00:11:22:33:44:55',
            'ssid': 'FreeWiFi-Trap',
            'detected_by': 1,
            'description': 'Critical rogue access point detected in office area',
            'signal_strength': -35,
            'packet_count': 250,
            'is_resolved': False,
            'detected_by_user': current_user.get('username', 'anonymous'),
            'created_at': datetime.now().isoformat()
        }
        
        # Broadcast to all connected WebSocket clients
        broadcast_threat_event(threat_data)
        
        return jsonify({
            'message': 'Threat simulated and broadcasted',
            'threat': threat_data,
            'broadcasted_to': 'all_connected_clients'
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to simulate threat: {str(e)}'}), 500


# ==================== Sensor Routes ====================

@sensors_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_sensors():
    """Get list of sensors"""
    try:
        mock_sensors = [
            {
                'id': 1,
                'name': 'Office Sensor 1',
                'hostname': 'sensor-office-1',
                'ip_address': '192.168.1.100',
                'mac_address': '00:1A:2B:3C:4D:5E',
                'location': 'Main Office',
                'is_active': True,
                'firmware_version': '2.1.0',
                'last_heartbeat': datetime.now().isoformat(),
                'status': 'online',
                'signal_strength': 95
            },
            {
                'id': 2,
                'name': 'Lobby Sensor 2',
                'hostname': 'sensor-lobby-1',
                'ip_address': '192.168.1.101',
                'mac_address': '00:1A:2B:3C:4D:5F',
                'location': 'Lobby',
                'is_active': True,
                'firmware_version': '2.1.0',
                'last_heartbeat': datetime.now().isoformat(),
                'status': 'online',
                'signal_strength': 87
            }
        ]
        
        return jsonify({
            'data': mock_sensors,
            'total': len(mock_sensors)
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch sensors: {str(e)}'}), 500


@sensors_bp.route('/<int:sensor_id>/health', methods=['GET'])
@jwt_required(optional=True)
def get_sensor_health(sensor_id):
    """Get sensor health metrics"""
    try:
        health = {
            'sensor_id': sensor_id,
            'status': 'online',
            'signal_strength': 95,
            'cpu_usage': 25.5,
            'memory_usage': 45.2,
            'uptime': 86400,  # 24 hours
            'last_heartbeat': datetime.now().isoformat(),
            'events_24h': 150,
            'threats_detected_24h': 2
        }
        return jsonify(health), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch sensor health: {str(e)}'}), 500


# ==================== Alert Routes ====================

@alerts_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_alerts():
    """Get list of alerts"""
    try:
        mock_alerts = [
            {
                'id': 1,
                'threat_id': 1,
                'message': 'Critical rogue AP detected',
                'is_read': False,
                'is_acknowledged': False,
                'created_at': datetime.now().isoformat()
            }
        ]
        return jsonify({'data': mock_alerts}), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch alerts: {str(e)}'}), 500


@alerts_bp.route('/<int:alert_id>/acknowledge', methods=['POST'])
@jwt_required(optional=True)
def acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    try:
        current_user = get_jwt_identity() or {}
        
        return jsonify({
            'message': 'Alert acknowledged',
            'alert_id': alert_id,
            'acknowledged_by': current_user.get('username', 'anonymous'),
            'acknowledged_at': datetime.now().isoformat()
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to acknowledge alert: {str(e)}'}), 500


# ==================== Analytics Routes ====================

@analytics_bp.route('/threat-stats', methods=['GET'])
@jwt_required(optional=True)
def get_threat_stats():
    """Get threat statistics"""
    try:
        stats = {
            'total_threats': 25,
            'threats_today': 3,
            'critical_threats': 2,
            'high_threats': 5,
            'medium_threats': 10,
            'low_threats': 8,
            'resolved_threats': 15,
            'active_threats': 10,
            'threat_types': {
                'rogue_ap': 10,
                'evil_twin': 5,
                'deauth_attack': 7,
                'signal_jamming': 3
            }
        }
        return jsonify(stats), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch threat stats: {str(e)}'}), 500


@analytics_bp.route('/trends', methods=['GET'])
@jwt_required(optional=True)
def get_trends():
    """Get historical trend data"""
    try:
        trends = {
            'daily_threats': [
                {'date': '2024-01-01', 'count': 3},
                {'date': '2024-01-02', 'count': 5},
                {'date': '2024-01-03', 'count': 2},
                {'date': '2024-01-04', 'count': 8},
                {'date': '2024-01-05', 'count': 4},
                {'date': '2024-01-06', 'count': 6},
                {'date': '2024-01-07', 'count': 3}
            ],
            'sensor_uptime': [
                {'sensor': 'Office Sensor 1', 'uptime': 99.8},
                {'sensor': 'Lobby Sensor 2', 'uptime': 99.5},
                {'sensor': 'Parking Sensor 3', 'uptime': 95.2}
            ]
        }
        return jsonify(trends), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch trends: {str(e)}'}), 500


# ==================== User Routes ====================

@users_bp.route('/profile', methods=['GET'])
@jwt_required(optional=True)
def get_user_profile():
    """Get current user's profile"""
    try:
        current_user = get_jwt_identity()
        
        profile = {
            'id': current_user['user_id'],
            'username': current_user['username'],
            'email': current_user['email'],
            'is_admin': current_user['is_admin'],
            'created_at': datetime.now().isoformat()
        }
        
        return jsonify(profile), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch profile: {str(e)}'}), 500


def register_blueprints(app):
    """Register all API blueprints"""
    from routes_dashboard import dashboard_bp
    from routes_topology import topology_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(threats_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(sensors_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(topology_bp)
