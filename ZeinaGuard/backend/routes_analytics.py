"""
Analytics API Routes for ZeinaGuard Pro
Provides advanced threat statistics and historical trends
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta
from sqlalchemy import func
from models import db, Threat, Sensor, SensorHealth

analytics_bp = Blueprint('analytics', __name__, url_prefix='/api/analytics')


@analytics_bp.route('/threat-stats', methods=['GET'])
@jwt_required(optional=True)
def get_threat_stats():
    """Get detailed threat statistics"""
    try:
        # Group by type
        type_stats = db.session.query(
            Threat.threat_type, func.count(Threat.id)
        ).group_by(Threat.threat_type).all()
        
        # Group by severity
        severity_stats = db.session.query(
            Threat.severity, func.count(Threat.id)
        ).group_by(Threat.severity).all()
        
        # Resolved vs Active
        resolved_count = Threat.query.filter_by(is_resolved=True).count()
        active_count = Threat.query.filter_by(is_resolved=False).count()
        
        return jsonify({
            'total_threats': resolved_count + active_count,
            'resolved_threats': resolved_count,
            'active_threats': active_count,
            'threat_types': {t[0]: t[1] for t in type_stats},
            'severity_levels': {s[0]: s[1] for s in severity_stats}
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch threat stats: {str(e)}'}), 500


@analytics_bp.route('/trends', methods=['GET'])
@jwt_required(optional=True)
def get_trends():
    """Get threat trends for the last 7 days"""
    try:
        days = 7
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Query threats by day
        threats_by_day = db.session.query(
            func.date(Threat.created_at).label('day'),
            func.count(Threat.id)
        ).filter(
            Threat.created_at >= start_date
        ).group_by('day').order_by('day').all()
        
        # Format for charts
        trends = []
        for i in range(days):
            d = (start_date + timedelta(days=i)).date()
            count = 0
            for row in threats_by_day:
                if row[0] == d:
                    count = row[1]
                    break
            trends.append({'date': d.isoformat(), 'count': count})
            
        return jsonify({
            'daily_threats': trends,
            'period': 'Last 7 days'
        }), 200
    
    except Exception as e:
        return jsonify({'error': f'Failed to fetch trends: {str(e)}'}), 500
