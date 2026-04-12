"""
Alert API Routes for ZeinaGuard Pro
Provides database-backed alert rule management and notifications
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from models import db, Alert, AlertRule
from auth import admin_required

alerts_bp = Blueprint('alerts', __name__, url_prefix='/api/alerts')


@alerts_bp.route('/', methods=['GET'])
@jwt_required(optional=True)
def get_alerts():
    """Get list of recent alerts"""
    try:
        limit = request.args.get('limit', default=50, type=int)
        
        alerts = Alert.query.order_by(Alert.created_at.desc()).limit(limit).all()
        
        alert_list = []
        for a in alerts:
            alert_list.append({
                'id': a.id,
                'threat_id': a.threat_id,
                'rule_id': a.rule_id,
                'message': a.message,
                'is_read': a.is_read,
                'is_acknowledged': a.is_acknowledged,
                'acknowledged_by': a.acknowledged_by,
                'acknowledged_at': a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                'created_at': a.created_at.isoformat() if a.created_at else None
            })
            
        return jsonify({
            'data': alert_list,
            'total': len(alert_list)
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch alerts: {str(e)}'}), 500


@alerts_bp.route('/rules', methods=['GET'])
@jwt_required(optional=True)
def get_alert_rules():
    """Get all alert rules"""
    try:
        rules = AlertRule.query.all()
        
        rule_list = []
        for r in rules:
            rule_list.append({
                'id': r.id,
                'name': r.name,
                'description': r.description,
                'threat_type': r.threat_type,
                'severity': r.severity,
                'is_enabled': r.is_enabled,
                'action_type': r.action_type,
                'created_at': r.created_at.isoformat() if r.created_at else None
            })
            
        return jsonify({
            'data': rule_list,
            'total': len(rule_list)
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch alert rules: {str(e)}'}), 500


@alerts_bp.route('/rules', methods=['POST'])
@jwt_required()
@admin_required
def create_alert_rule():
    """Create a new alert rule (requires admin)"""
    try:
        data = request.get_json()
        
        if not data or not data.get('name'):
            return jsonify({'error': 'Rule name is required'}), 400
            
        new_rule = AlertRule(
            name=data['name'],
            description=data.get('description'),
            threat_type=data.get('threat_type'),
            severity=data.get('severity'),
            is_enabled=data.get('is_enabled', True),
            action_type=data.get('action_type', 'alert'),
            created_by=get_jwt_identity().get('user_id')
        )
        
        db.session.add(new_rule)
        db.session.commit()
        
        return jsonify({
            'message': 'Alert rule created successfully',
            'rule_id': new_rule.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create alert rule: {str(e)}'}), 500


@alerts_bp.route('/<int:alert_id>/acknowledge', methods=['POST'])
@jwt_required()
def acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    try:
        current_user = get_jwt_identity()
        alert = Alert.query.get(alert_id)
        
        if not alert:
            return jsonify({'error': 'Alert not found'}), 404
            
        alert.is_acknowledged = True
        alert.acknowledged_by = current_user.get('user_id')
        alert.acknowledged_at = datetime.utcnow()
        alert.is_read = True
        
        db.session.commit()
        
        return jsonify({
            'message': 'Alert acknowledged',
            'alert_id': alert_id,
            'acknowledged_by': current_user.get('username'),
            'acknowledged_at': alert.acknowledged_at.isoformat()
        }), 200
    
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to acknowledge alert: {str(e)}'}), 500
