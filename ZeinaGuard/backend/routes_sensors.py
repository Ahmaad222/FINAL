"""
Sensors API Routes for ZeinaGuard Pro
Handles sensor registration and monitoring metrics
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from models import db, Sensor, SensorHealth
from datetime import datetime
from sqlalchemy import desc

sensors_bp = Blueprint('sensors', __name__, url_prefix='/api/sensors')


@sensors_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_sensors():
    try:
        sensors = Sensor.query.all()
        result = []

        for s in sensors:
            health = SensorHealth.query.filter_by(sensor_id=s.id)\
                .order_by(desc(SensorHealth.created_at)).first()

            status = health.status if health else ('online' if s.is_active else 'offline')

            result.append({
                'id': s.id,
                'hostname': s.hostname or s.name,
                'name': s.name,
                'location': s.location or 'Unknown',
                'status': status,
                'signal_strength': health.signal_strength if health else -100,
                'cpu_usage': health.cpu_usage if health else 0,
                'memory_usage': health.memory_usage if health else 0,
                'uptime_percent': 100,
                'last_seen': (
                    health.last_heartbeat.isoformat()
                    if health and health.last_heartbeat
                    else s.updated_at.isoformat()
                ),
                'packet_count': 0,
                'coverage_area': 'Standard Room'
            })

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@sensors_bp.route('/register', methods=['POST'])
@jwt_required(optional=True)
def register_sensor():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON'}), 400

        name = data.get('name')
        hostname = data.get('hostname')
        ip_address = data.get('ip_address')
        mac_address = data.get('mac_address')
        location = data.get('location')

        if not name or not hostname:
            return jsonify({'error': 'Name and hostname are required'}), 400

        sensor = Sensor.query.filter_by(hostname=hostname).first()

        if sensor:
            sensor.name = name
            sensor.ip_address = ip_address
            sensor.mac_address = mac_address
            sensor.location = location
            sensor.updated_at = datetime.utcnow()
        else:
            sensor = Sensor(
                name=name,
                hostname=hostname,
                ip_address=ip_address,
                mac_address=mac_address,
                location=location,
                is_active=True
            )
            db.session.add(sensor)

        db.session.commit()

        return jsonify({
            'message': 'Sensor registered successfully',
            'sensor_id': sensor.id
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@sensors_bp.route('/<int:sensor_id>/health', methods=['POST'])
@jwt_required(optional=True)
def update_sensor_health(sensor_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing JSON'}), 400

        health = SensorHealth(
            sensor_id=sensor_id,
            status=data.get('status', 'online'),
            signal_strength=data.get('signal_strength'),
            cpu_usage=data.get('cpu_usage'),
            memory_usage=data.get('memory_usage'),
            uptime=data.get('uptime'),
            last_heartbeat=datetime.utcnow()
        )

        db.session.add(health)

        sensor = Sensor.query.get(sensor_id)
        if sensor:
            sensor.is_active = (health.status == 'online')
            sensor.updated_at = datetime.utcnow()

        db.session.commit()

        return jsonify({'message': 'Sensor health updated'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500