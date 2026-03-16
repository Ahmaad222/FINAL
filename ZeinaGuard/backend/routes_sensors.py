from flask import Blueprint, jsonify, request
from auth import token_required
from models import db, Sensor

sensors_bp = Blueprint(
    "sensors",
    __name__,
    url_prefix="/api/sensors"
)


# -----------------------------
# Register Sensor
# -----------------------------
@sensors_bp.route("/register", methods=["POST"])
@token_required
def register_sensor(current_user):

    data = request.get_json()

    sensor_id = data.get("id")

    name = data.get("name")

    location = data.get("location", "unknown")

    if not sensor_id or not name:

        return jsonify({

            "error": "sensor id and name required"

        }), 400

    sensor = Sensor.query.get(sensor_id)

    if not sensor:

        sensor = Sensor(

            id=sensor_id,
            name=name,
            location=location,
            is_active=True

        )

        db.session.add(sensor)

    else:

        sensor.name = name
        sensor.location = location
        sensor.is_active = True

    db.session.commit()

    return jsonify({

        "message": "sensor registered",
        "id": sensor_id

    })


# -----------------------------
# Get Sensors
# -----------------------------
@sensors_bp.route("/", methods=["GET"])
@token_required
def get_sensors(current_user):

    sensors = Sensor.query.all()

    return jsonify([

        {

            "id": s.id,
            "name": s.name,
            "location": s.location,
            "status": "online" if s.is_active else "offline"

        }

        for s in sensors

    ])
