from flask import Blueprint, jsonify
from auth import token_required
import datetime

threats_bp = Blueprint('threats', __name__)

@threats_bp.route('/api/threats', methods=['GET'])
@token_required
def get_threats(current_user):
    return jsonify([
        {
            "id": "TH-101",
            "type": "Rogue AP",
            "ssid": "Hacker_Zone_Free",
            "severity": "Critical",
            "status": "Detected",
            "timestamp": datetime.datetime.now().isoformat()
        },
        {
            "id": "TH-102",
            "type": "Evil Twin",
            "ssid": "ZeinaGuard_Staff",
            "severity": "High",
            "status": "Mitigated",
            "timestamp": datetime.datetime.now().isoformat()
        }
    ])