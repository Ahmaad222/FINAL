"""
WebSocket Server for ZeinaGuard Pro
Real-time threat events and sensor status updates via Socket.io
"""

import os
import json
from datetime import datetime
from flask_socketio import SocketIO, emit, join_room, leave_room
from redis import Redis
from functools import wraps
from flask import request

# Redis connection for event bus
redis_client = Redis.from_url(
    os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
    decode_responses=True
)

# Store connected clients
connected_clients = {}


def init_socketio(app):
    """Initialize Socket.io with Flask app"""
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        ping_timeout=60,
        ping_interval=25,
        async_mode='threading'
    )
    
    # Connection events
    @socketio.on('connect')
    def handle_connect(data):
        """Handle client connection"""
        client_id = request.sid
        connected_clients[client_id] = {
            'connected_at': datetime.now().isoformat(),
            'subscriptions': []
        }
        emit('connection_response', {
            'data': 'Connected to ZeinaGuard Pro WebSocket',
            'client_id': client_id
        })
        print(f"[WebSocket] Client connected: {client_id}")
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        client_id = request.sid
        if client_id in connected_clients:
            del connected_clients[client_id]
        print(f"[WebSocket] Client disconnected: {client_id}")
    
    # Threat events
    @socketio.on('subscribe_threats')
    def handle_subscribe_threats():
        """Subscribe to threat events"""
        client_id = request.sid
        if client_id in connected_clients:
            connected_clients[client_id]['subscriptions'].append('threats')
        emit('subscription_response', {'channel': 'threats', 'subscribed': True})
        print(f"[WebSocket] Client {client_id} subscribed to threats")
    
    @socketio.on('unsubscribe_threats')
    def handle_unsubscribe_threats():
        """Unsubscribe from threat events"""
        client_id = request.sid
        if client_id in connected_clients:
            if 'threats' in connected_clients[client_id]['subscriptions']:
                connected_clients[client_id]['subscriptions'].remove('threats')
        emit('subscription_response', {'channel': 'threats', 'subscribed': False})
    
    # Sensor status
    @socketio.on('subscribe_sensors')
    def handle_subscribe_sensors():
        """Subscribe to sensor status updates"""
        client_id = request.sid
        if client_id in connected_clients:
            connected_clients[client_id]['subscriptions'].append('sensors')
        emit('subscription_response', {'channel': 'sensors', 'subscribed': True})
        print(f"[WebSocket] Client {client_id} subscribed to sensors")
    
    @socketio.on('unsubscribe_sensors')
    def handle_unsubscribe_sensors():
        """Unsubscribe from sensor updates"""
        client_id = request.sid
        if client_id in connected_clients:
            if 'sensors' in connected_clients[client_id]['subscriptions']:
                connected_clients[client_id]['subscriptions'].remove('sensors')
        emit('subscription_response', {'channel': 'sensors', 'subscribed': False})
    
    return socketio


def broadcast_threat_event(threat_data):
    """
    Broadcast threat event to all connected clients
    Called from Flask routes when a threat is detected
    
    Args:
        threat_data: Dictionary with threat information
    """
    event = {
        'type': 'threat_detected',
        'timestamp': datetime.now().isoformat(),
        'severity': threat_data.get('severity', 'unknown'),
        'threat_type': threat_data.get('threat_type', 'unknown'),
        'data': threat_data
    }
    
    # Store in Redis for persistence (optional)
    try:
        redis_client.lpush('threat_events', json.dumps(event))
        redis_client.ltrim('threat_events', 0, 999)  # Keep last 1000
    except Exception as e:
        print(f"[Redis] Error storing threat event: {e}")
    
    # Broadcast to all connected clients
    from flask import current_app
    socketio = current_app.socketio
    socketio.emit('threat_event', event, to=None)


def broadcast_sensor_status(sensor_data):
    """
    Broadcast sensor status update to all connected clients
    
    Args:
        sensor_data: Dictionary with sensor status
    """
    event = {
        'type': 'sensor_status',
        'timestamp': datetime.now().isoformat(),
        'data': sensor_data
    }
    
    # Store in Redis
    try:
        redis_client.hset(f"sensor:{sensor_data['sensor_id']}", 
                         mapping={'status': json.dumps(event)})
    except Exception as e:
        print(f"[Redis] Error storing sensor status: {e}")
    
    # Broadcast to all connected clients
    from flask import current_app
    socketio = current_app.socketio
    socketio.emit('sensor_status', event, to=None)


def get_connected_clients_count():
    """Get number of connected WebSocket clients"""
    return len(connected_clients)


def get_client_subscriptions(client_id):
    """Get subscriptions for specific client"""
    if client_id in connected_clients:
        return connected_clients[client_id]['subscriptions']
    return []
