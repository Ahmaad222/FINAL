import os
import json
from datetime import datetime

from flask import Flask, request
from flask_socketio import SocketIO, emit
from redis import Redis


# =========================
# Flask App
# =========================

app = Flask(__name__)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_timeout=60,
    ping_interval=25,
    async_mode="eventlet"
)

# =========================
# Redis
# =========================

redis_client = Redis.from_url(
    os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True
)

# =========================
# Storage
# =========================

connected_clients = {}
connected_sensors = {}

# =========================
# WebSocket Events
# =========================

@socketio.on("connect")
def handle_connect():

    client_id = request.sid

    connected_clients[client_id] = {
        "connected_at": datetime.now().isoformat(),
        "subscriptions": []
    }

    print(f"[WebSocket] Client connected: {client_id}")

    emit("connection_response", {
        "client_id": client_id,
        "message": "Connected to ZeinaGuard"
    })


@socketio.on("disconnect")
def handle_disconnect():

    client_id = request.sid

    if client_id in connected_clients:
        del connected_clients[client_id]

    if client_id in connected_sensors:

        sensor = connected_sensors[client_id]

        broadcast_sensor_status({
            "sensor_id": sensor["sensor_id"],
            "name": sensor["name"],
            "status": "offline"
        })

        del connected_sensors[client_id]

    print(f"[WebSocket] Client disconnected: {client_id}")


# =========================
# Sensor Register
# =========================

@socketio.on("sensor_register")
def handle_sensor_register(data):

    client_id = request.sid

    sensor_id = data.get("sensor_id", client_id)
    name = data.get("name", "ZeinaGuard Sensor")

    connected_sensors[client_id] = {
        "sensor_id": sensor_id,
        "name": name,
        "connected_at": datetime.now().isoformat()
    }

    print(f"[Sensor] Registered: {sensor_id}")

    sensor_data = {
        "sensor_id": sensor_id,
        "name": name,
        "status": "online"
    }

    broadcast_sensor_status(sensor_data)


# =========================
# Threat Events
# =========================

@socketio.on("new_threat")
def handle_new_threat(data):

    print(f"[Threat] {data}")

    broadcast_threat_event(data)


# =========================
# Broadcast Threat
# =========================

def broadcast_threat_event(threat_data):

    event = {
        "type": "threat_detected",
        "timestamp": datetime.now().isoformat(),
        "severity": threat_data.get("severity", "unknown"),
        "threat_type": threat_data.get("threat_type", "unknown"),
        "data": threat_data
    }

    try:

        redis_client.lpush("threat_events", json.dumps(event))
        redis_client.ltrim("threat_events", 0, 1000)

    except Exception as e:
        print(f"[Redis] Threat store error: {e}")

    socketio.emit("threat_event", event)


# =========================
# Broadcast Sensor Status
# =========================

def broadcast_sensor_status(sensor_data):

    event = {
        "type": "sensor_status",
        "timestamp": datetime.now().isoformat(),
        "data": sensor_data
    }

    try:

        redis_client.hset(
            "sensors",
            sensor_data["sensor_id"],
            json.dumps(event)
        )

    except Exception as e:
        print(f"[Redis] Sensor store error: {e}")

    socketio.emit("sensor_status", event)


# =========================
# Run Server
# =========================

if __name__ == "__main__":

    print("🚀 ZeinaGuard WebSocket Server running on port 5001")

    socketio.run(
        app,
        host="0.0.0.0",
        port=5001
    )
