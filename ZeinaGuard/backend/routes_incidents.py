"""
Incident API Routes for ZeinaGuard Pro
Provides database-backed incident response tracking
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from models import db, Incident, IncidentEvent
from auth import admin_required

incidents_bp = Blueprint('incidents', __name__, url_prefix='/api/incidents')


@incidents_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_incidents():
    """Get list of incidents with filtering"""
    try:
        status = request.args.get('status')
        severity = request.args.get('severity')
        
        query = Incident.query
        
        if status:
            query = query.filter_by(status=status)
        if severity:
            query = query.filter_by(severity=severity)
            
        incidents = query.order_by(Incident.created_at.desc()).all()
        
        incident_list = []
        for i in incidents:
            incident_list.append({
                'id': i.id,
                'title': i.title,
                'severity': i.severity,
                'status': i.status,
                'assigned_to': i.assigned_to,
                'created_at': i.created_at.isoformat() if i.created_at else None,
                'updated_at': i.updated_at.isoformat() if i.updated_at else None
            })
            
        return jsonify({
            'data': incident_list,
            'total': len(incident_list)
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch incidents: {str(e)}'}), 500


@incidents_bp.route('/<int:incident_id>', methods=['GET'])
@jwt_required(optional=True)
def get_incident(incident_id):
    """Get detailed incident information"""
    try:
        incident = Incident.query.get(incident_id)
        if not incident:
            return jsonify({'error': 'Incident not found'}), 404
            
        events = []
        for e in incident.events:
            events.append({
                'id': e.id,
                'event_type': e.event_type,
                'event_data': e.event_data,
                'created_at': e.created_at.isoformat() if e.created_at else None
            })
            
        return jsonify({
            'id': incident.id,
            'title': incident.title,
            'description': incident.description,
            'severity': incident.severity,
            'status': incident.status,
            'threat_ids': incident.threat_ids,
            'assigned_to': incident.assigned_to,
            'created_at': incident.created_at.isoformat() if incident.created_at else None,
            'updated_at': incident.updated_at.isoformat() if incident.updated_at else None,
            'events': events
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch incident: {str(e)}'}), 500


@incidents_bp.route('/', methods=['POST'])
@jwt_required()
def create_incident():
    """Create a new incident"""
    try:
        data = request.get_json()
        current_user = get_jwt_identity()
        
        if not data or not data.get('title'):
            return jsonify({'error': 'Incident title is required'}), 400
            
        new_incident = Incident(
            title=data['title'],
            description=data.get('description'),
            severity=data.get('severity', 'medium'),
            status='open',
            threat_ids=data.get('threat_ids', []),
            created_by=current_user.get('user_id'),
            assigned_to=data.get('assigned_to')
        )
        
        db.session.add(new_incident)
        db.session.commit()
        
        return jsonify({
            'message': 'Incident created successfully',
            'incident_id': new_incident.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create incident: {str(e)}'}), 500
