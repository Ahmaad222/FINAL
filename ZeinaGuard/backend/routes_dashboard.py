from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from models import Sensor, SensorHealth, db
from sqlalchemy import desc

dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    url_prefix="/api/dashboard"
)


# -----------------------------
# Dashboard Overview
# -----------------------------
@dashboard_bp.route("/overview", methods=["GET"])
@jwt_required()
def overview():

    total_sensors = Sensor.query.count()

    online = Sensor.query.filter_by(is_active=True).count()

    offline = Sensor.query.filter_by(is_active=False).count()

    return jsonify({

        "sensors": {

            "total": total_sensors,
            "online": online,
            "offline": offline

        },

        "threats": {

            "critical": 0,
            "high": 0,
            "total": 0

        },

        "incidents": {

            "open": 0,
            "resolved": 0

        }

    })


# -----------------------------
# Sensor Health
# -----------------------------
@dashboard_bp.route("/sensor-health", methods=["GET"])
@jwt_required()
def sensor_health():

    sensors = Sensor.query.all()

    data = []

    for s in sensors:

        health = SensorHealth.query\
            .filter_by(sensor_id=s.id)\
            .order_by(desc(SensorHealth.created_at))\
            .first()

        if health:

            data.append({

                "sensor_id": s.id,
                "name": s.name,
                "location": s.location,
                "status": health.status,
                "signal": health.signal_strength,
                "cpu": health.cpu_usage,
                "memory": health.memory_usage,
                "uptime": health.uptime

            })

        else:

            data.append({

                "sensor_id": s.id,
                "name": s.name,
                "location": s.location,
                "status": "unknown"

            })

    return jsonify({

        "sensors": data,
        "count": len(data)

    })
