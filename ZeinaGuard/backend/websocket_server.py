"""
WebSocket Server for ZeinaGuard Pro
Handles communication between Sensors and Dashboard
"""

import os
from datetime import datetime
from flask_socketio import SocketIO, emit
from redis import Redis
from flask import request, current_app
from models import db, Threat, ThreatEvent, Sensor

# --------------------------------
# Redis Connection (optional)
# --------------------------------
try:
    redis_client = Redis.from_url(
        os.getenv('REDIS_URL', 'redis://localhost:6379/0'),
        decode_responses=True
    )
except Exception:
    redis_client = None

# --------------------------------
# Connected Clients
# --------------------------------
connected_clients = {}


# --------------------------------
# Initialize SocketIO
# --------------------------------
def init_socketio(app):

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading"
    )

    # ----------------------------
    # Client Connected
    # ----------------------------
    @socketio.on("connect")
    def handle_connect():

        client_id = request.sid

        connected_clients[client_id] = {
            "connected_at": datetime.now().isoformat()
        }

        print(f"[WebSocket] 🟢 Client Connected: {client_id}")

    # ----------------------------
    # Client Disconnected
    # ----------------------------
    @socketio.on("disconnect")
    def handle_disconnect():

        client_id = request.sid

        if client_id in connected_clients:
            del connected_clients[client_id]

        print(f"[WebSocket] 🔴 Client Disconnected: {client_id}")

    # ----------------------------
    # Sensor Registration
    # ----------------------------
    @socketio.on("sensor_register")
    def handle_sensor_register(data):

        sensor_id = data.get("sensor_id")

        print(f"[WebSocket] 🛰️ Sensor Registered: {sensor_id}")

        emit("registration_success", {
            "status": "registered",
            "sensor_id": sensor_id
        })

    # ----------------------------
    # Receive Threat from Sensor
    # ----------------------------
    @socketio.on("new_threat")
    def handle_new_threat(payload):

        print(f"[WebSocket] 🚨 Received Threat: {payload.get('ssid')} from Sensor")

        with app.app_context():

            try:

                new_threat = Threat(
                    threat_type=payload.get("threat_type", "UNKNOWN"),
                    severity=payload.get("severity", "HIGH"),
                    source_mac=payload.get("source_mac"),
                    ssid=payload.get("ssid"),
                    description="Detected via Sensor WebSocket"
                )

                db.session.add(new_threat)
                db.session.commit()
                print(f"[WebSocket] ✅ Threat '{payload.get('ssid')}' saved to PostgreSQL database (ID: {new_threat.id})")

                broadcast_data = {
                    "id": new_threat.id,
                    "type": "threat_detected",
                    "timestamp": datetime.now().isoformat(),
                    "data": payload
                }

                socketio.emit("threat_event", broadcast_data)

                print(f"[WebSocket] 🚀 Broadcasted Threat ID: {new_threat.id}")

            except Exception as e:

                db.session.rollback()

                print(f"[WebSocket] ❌ Error saving threat: {e}")

    # ----------------------------
    # Receive Network Scan Data
    # ----------------------------
    @socketio.on("network_scan")
    def handle_network_scan(payload):
        """Processes enriched network data from sensor."""
        sensor_name = payload.get("sensor_id", "sensor1")
        print(f"[WebSocket] 📡 Received Scan Data: {payload.get('ssid')} from {sensor_name}")
        
        with app.app_context():
            try:
                from models import NetworkTopology, Sensor, db
                
                # 🛠️ Find or Auto-Create the sensor
                sensor = Sensor.query.filter_by(name=sensor_name).first()
                if not sensor:
                    print(f"[WebSocket] 🆕 Auto-registering new sensor: {sensor_name}")
                    sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
                    db.session.add(sensor)
                    db.session.commit()
                
                # 🛠️ Find or Create the topology record for this sensor
                topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
                if not topology:
                    topology = NetworkTopology(sensor_id=sensor.id, discovered_networks=[], discovered_devices=[])
                    db.session.add(topology)
                
                # Update topology with latest scan
                current_networks = topology.discovered_networks or []
                network_info = {
                    "ssid": payload.get("ssid"),
                    "bssid": payload.get("bssid"),
                    "channel": payload.get("channel"),
                    "signal": payload.get("signal"),
                    "distance": payload.get("distance"),
                    "auth": payload.get("auth"),
                    "wps": payload.get("wps"),
                    "manufacturer": payload.get("manufacturer"),
                    "uptime": payload.get("uptime"),
                    "raw_beacon": payload.get("raw_beacon"),
                    "elapsed_time": payload.get("elapsed_time"),
                    "status": payload.get("status"),
                    "score": payload.get("score"),
                    "last_seen": payload.get("timestamp")
                }

                
                # Update if exists, otherwise append
                found = False
                for i, net in enumerate(current_networks):
                    if net.get("bssid") == payload.get("bssid"):
                        current_networks[i] = network_info
                        found = True
                        break
                
                if not found:
                    current_networks.append(network_info)
                
                topology.discovered_networks = current_networks
                
                # 🛠️ NEW: Save every individual scan event to the Threat table for history
                # This ensures the user sees ALL data in the database
                severity_map = {"ROGUE": "HIGH", "SUSPICIOUS": "MEDIUM", "LEGIT": "INFO"}
                
                history_entry = Threat(
                    threat_type=payload.get("status", "SCAN"),
                    severity=severity_map.get(payload.get("status"), "INFO"),
                    source_mac=payload.get("bssid"),
                    ssid=payload.get("ssid"),
                    detected_by=sensor.id,
                    description=f"Scan Log: {payload.get('manufacturer')} on CH {payload.get('channel')}"
                )
                db.session.add(history_entry)
                
                db.session.commit()
                print(f"[WebSocket] ✅ Full scan data for '{payload.get('ssid')}' logged to history.")
                
                # Broadcast to UI
                socketio.emit("new_scan_data", payload)
                
            except Exception as e:
                print(f"[WebSocket] ❌ Error processing scan data: {e}")
                db.session.rollback()

    return socketio


# --------------------------------
# Broadcast Threat Event
# --------------------------------
def broadcast_threat_event(threat_data):

    socketio = current_app.socketio

    socketio.emit("threat_event", threat_data)

    print("[WebSocket] 📡 Threat broadcasted to dashboard")


# --------------------------------
# Broadcast Sensor Status
# --------------------------------
def broadcast_sensor_status(sensor_data):

    socketio = current_app.socketio

    socketio.emit("sensor_status", sensor_data)

    print("[WebSocket] 📡 Sensor status broadcasted")