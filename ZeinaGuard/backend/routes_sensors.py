"""
Sensor API Routes for ZeinaGuard Pro
Provides database-backed sensor management and monitoring
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from models import db, Sensor, SensorHealth
from auth import admin_required

sensors_bp = Blueprint('sensors', __name__, url_prefix='/api/sensors')


@sensors_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_sensors():
    """Get list of sensors with status and latest metrics"""
    try:
        sensors = Sensor.query.all()
        
        sensor_list = []
        for s in sensors:
            # Get latest health record
            latest_health = SensorHealth.query.filter_by(sensor_id=s.id).order_by(SensorHealth.created_at.desc()).first()
            
            sensor_list.append({
                'id': s.id,
                'name': s.name,
                'hostname': s.hostname,
                'ip_address': s.ip_address,
                'mac_address': s.mac_address,
                'location': s.location,
                'is_active': s.is_active,
                'status': latest_health.status if latest_health else ('online' if s.is_active else 'offline'),
                'signal_strength': latest_health.signal_strength if latest_health else None,
                'last_heartbeat': latest_health.last_heartbeat.isoformat() if latest_health and latest_health.last_heartbeat else None,
                'firmware_version': s.firmware_version
            })
            
        return jsonify({
            'data': sensor_list,
            'total': len(sensor_list)
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch sensors: {str(e)}'}), 500


@sensors_bp.route('/<int:sensor_id>', methods=['GET'])
@jwt_required(optional=True)
def get_sensor(sensor_id):
    """Get detailed sensor information"""
    try:
        sensor = Sensor.query.get(sensor_id)
        if not sensor:
            return jsonify({'error': 'Sensor not found'}), 404
            
        latest_health = SensorHealth.query.filter_by(sensor_id=sensor.id).order_by(SensorHealth.created_at.desc()).first()
        
        return jsonify({
            'id': sensor.id,
            'name': sensor.name,
            'hostname': sensor.hostname,
            'ip_address': sensor.ip_address,
            'mac_address': sensor.mac_address,
            'location': sensor.location,
            'is_active': sensor.is_active,
            'firmware_version': sensor.firmware_version,
            'health': {
                'status': latest_health.status if latest_health else 'unknown',
                'signal_strength': latest_health.signal_strength if latest_health else None,
                'cpu_usage': latest_health.cpu_usage if latest_health else None,
                'memory_usage': latest_health.memory_usage if latest_health else None,
                'uptime': latest_health.uptime if latest_health else None,
                'last_heartbeat': latest_health.last_heartbeat.isoformat() if latest_health and latest_health.last_heartbeat else None
            }
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch sensor: {str(e)}'}), 500


@sensors_bp.route('/register', methods=['POST'])
@jwt_required()
@admin_required
def register_sensor():
    """Register a new sensor (requires admin)"""
    try:
        data = request.get_json()
        
        if not data or not data.get('name') or not data.get('mac_address'):
            return jsonify({'error': 'Name and MAC address are required'}), 400
            
        # Check if MAC already exists
        existing = Sensor.query.filter_by(mac_address=data['mac_address']).first()
        if existing:
            return jsonify({'error': 'Sensor with this MAC address already registered'}), 400
            
        new_sensor = Sensor(
            name=data['name'],
            hostname=data.get('hostname'),
            ip_address=data.get('ip_address'),
            mac_address=data['mac_address'],
            location=data.get('location'),
            firmware_version=data.get('firmware_version', '1.0.0'),
            is_active=True
        )
        
        db.session.add(new_sensor)
        db.session.commit()
        
        return jsonify({
            'message': 'Sensor registered successfully',
            'sensor_id': new_sensor.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to register sensor: {str(e)}'}), 500


@sensors_bp.route('/<int:sensor_id>/heartbeat', methods=['POST'])
def sensor_heartbeat(sensor_id):
    """Endpoint for sensors to report heartbeat and health metrics"""
    try:
        sensor = Sensor.query.get(sensor_id)
        if not sensor:
            return jsonify({'error': 'Sensor not found'}), 404
            
        data = request.get_json()
        
        # Create new health record
        health = SensorHealth(
            sensor_id=sensor.id,
            status=data.get('status', 'online'),
            signal_strength=data.get('signal_strength'),
            cpu_usage=data.get('cpu_usage'),
            memory_usage=data.get('memory_usage'),
            uptime=data.get('uptime'),
            last_heartbeat=datetime.utcnow()
        )
        
        db.session.add(health)
        
        # Update sensor status
        sensor.is_active = data.get('status') == 'online'
        sensor.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Broadcast via WebSocket if needed
        from websocket_server import broadcast_sensor_status
        broadcast_sensor_status({
            'sensor_id': sensor.id,
            'status': health.status,
            'last_heartbeat': health.last_heartbeat.isoformat()
        })
        
        return jsonify({'message': 'Heartbeat received'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to process heartbeat: {str(e)}'}), 500
