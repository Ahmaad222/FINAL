"""
Threat API Routes for ZeinaGuard Pro
Provides database-backed threat monitoring and management
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from models import db, Threat, ThreatEvent, Sensor
from auth import admin_required

threats_bp = Blueprint('threats', __name__, url_prefix='/api/threats')


@threats_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_threats():
    """Get list of threats with optional filtering"""
    try:
        # Query parameters
        limit = request.args.get('limit', default=50, type=int)
        offset = request.args.get('offset', default=0, type=int)
        severity = request.args.get('severity', default=None, type=str)
        is_resolved = request.args.get('resolved', default=None, type=str)
        
        query = Threat.query
        
        # Filter by severity
        if severity:
            query = query.filter_by(severity=severity)
        
        # Filter by resolved status
        if is_resolved is not None:
            resolved_bool = is_resolved.lower() == 'true'
            query = query.filter_by(is_resolved=resolved_bool)
        
        # Order by latest
        query = query.order_by(Threat.created_at.desc())
        
        # Pagination
        total = query.count()
        threats = query.offset(offset).limit(limit).all()
        
        threat_list = []
        for t in threats:
            threat_list.append({
                'id': t.id,
                'threat_type': t.threat_type,
                'severity': t.severity,
                'source_mac': t.source_mac,
                'target_mac': t.target_mac,
                'ssid': t.ssid,
                'detected_by': t.detected_by,
                'description': t.description,
                'is_resolved': t.is_resolved,
                'created_at': t.created_at.isoformat() if t.created_at else None
            })
        
        return jsonify({
            'data': threat_list,
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
    """Get threat details including events"""
    try:
        threat = Threat.query.get(threat_id)
        if not threat:
            return jsonify({'error': 'Threat not found'}), 404
            
        events = []
        for e in threat.events:
            events.append({
                'id': e.id,
                'timestamp': e.time.isoformat() if e.time else None,
                'signal_strength': e.signal_strength,
                'packet_count': e.packet_count,
                'event_data': e.event_data
            })
            
        return jsonify({
            'id': threat.id,
            'threat_type': threat.threat_type,
            'severity': threat.severity,
            'source_mac': threat.source_mac,
            'target_mac': threat.target_mac,
            'ssid': threat.ssid,
            'detected_by': threat.detected_by,
            'description': threat.description,
            'is_resolved': threat.is_resolved,
            'created_at': threat.created_at.isoformat() if threat.created_at else None,
            'events': events
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch threat: {str(e)}'}), 500


@threats_bp.route('/<int:threat_id>/resolve', methods=['POST'])
@jwt_required()
def resolve_threat(threat_id):
    """Mark threat as resolved"""
    try:
        current_user = get_jwt_identity()
        threat = Threat.query.get(threat_id)
        
        if not threat:
            return jsonify({'error': 'Threat not found'}), 404
            
        threat.is_resolved = True
        threat.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Threat resolved successfully',
            'threat_id': threat_id,
            'resolved_by': current_user.get('username'),
            'resolved_at': datetime.utcnow().isoformat()
        }), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to resolve threat: {str(e)}'}), 500


@threats_bp.route('/<int:threat_id>/block', methods=['POST'])
@jwt_required()
@admin_required
def block_threat(threat_id):
    """Block/whitelist a threat source (requires admin)"""
    try:
        from models import BlockedDevice
        threat = Threat.query.get(threat_id)
        
        if not threat:
            return jsonify({'error': 'Threat not found'}), 404
            
        if not threat.source_mac:
            return jsonify({'error': 'Threat has no source MAC address'}), 400
            
        data = request.get_json()
        action = data.get('action', 'block')
        
        if action == 'block':
            # Add to blocked devices
            existing = BlockedDevice.query.filter_by(mac_address=threat.source_mac).first()
            if not existing:
                blocked = BlockedDevice(
                    mac_address=threat.source_mac,
                    device_name=threat.ssid or 'Unknown Device',
                    reason=f'Blocked from threat {threat.id}: {threat.threat_type}',
                    blocked_by=get_jwt_identity().get('user_id')
                )
                db.session.add(blocked)
                db.session.commit()
        
        return jsonify({
            'message': f'Source {threat.source_mac} {action}ed successfully',
            'threat_id': threat_id,
            'action': action,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to block threat: {str(e)}'}), 500


@threats_bp.route('/demo/simulate-threat', methods=['POST'])
@jwt_required(optional=True)
def simulate_threat():
    """
    Demo endpoint to simulate a real-time threat detection
    Broadcasts threat event via WebSocket and saves to DB
    """
    from websocket_server import broadcast_threat_event
    try:
        current_user = get_jwt_identity() or {}
        
        # Create threat in DB
        new_threat = Threat(
            threat_type='rogue_ap',
            severity='critical',
            source_mac='00:11:22:33:44:55',
            ssid='FreeWiFi-Trap',
            description='Critical rogue access point detected in office area',
            detected_by=1, # Default sensor
            is_resolved=False
        )
        db.session.add(new_threat)
        db.session.commit()
        
        # Create threat event
        event = ThreatEvent(
            threat_id=new_threat.id,
            sensor_id=1,
            packet_count=250,
            signal_strength=-35,
            event_data={'ssid': 'FreeWiFi-Trap', 'channel': 6}
        )
        db.session.add(event)
        db.session.commit()
        
        # Prepare broadcast data
        threat_data = {
            'id': new_threat.id,
            'threat_type': new_threat.threat_type,
            'severity': new_threat.severity,
            'source_mac': new_threat.source_mac,
            'ssid': new_threat.ssid,
            'detected_by': new_threat.detected_by,
            'description': new_threat.description,
            'signal_strength': -35,
            'packet_count': 250,
            'is_resolved': False,
            'created_at': new_threat.created_at.isoformat()
        }
        
        # Broadcast via WebSocket
        broadcast_threat_event(threat_data)
        
        return jsonify({
            'message': 'Threat simulated, saved to DB, and broadcasted',
            'threat': threat_data
        }), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to simulate threat: {str(e)}'}), 500
