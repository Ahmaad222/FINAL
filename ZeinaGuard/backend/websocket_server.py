"""
WebSocket Server for ZeinaGuard Pro
Handles communication between Sensors and Dashboard
"""

import os
import time
import threading
from datetime import datetime
from flask_socketio import SocketIO, emit
from redis import Redis
from flask import request, current_app
from models import db, Threat, Sensor

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
# Deduplication Cache
# --------------------------------
LAST_SEEN_CACHE = {}
COOLDOWN = 60  # seconds

# --------------------------------
# Cache Cleanup Thread
# --------------------------------
def cleanup_cache():
    while True:
        now = time.time()
        for bssid in list(LAST_SEEN_CACHE.keys()):
            if now - LAST_SEEN_CACHE[bssid] > 120:
                del LAST_SEEN_CACHE[bssid]
        time.sleep(30)

threading.Thread(target=cleanup_cache, daemon=True).start()


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
    # Receive Network Scan Data
    # ----------------------------
    @socketio.on("network_scan")
    def handle_network_scan(payload):

        sensor_name = payload.get("sensor_id", "sensor1")

        print(f"[RECEIVED] SSID={payload.get('ssid')} "
              f"BSSID={payload.get('bssid')} SENSOR={sensor_name}")

        with app.app_context():
            try:
                from models import NetworkTopology

                # ----------------------------
                # Sensor Handling
                # ----------------------------
                sensor = Sensor.query.filter_by(name=sensor_name).first()
                if not sensor:
                    print(f"[WebSocket] 🆕 Auto-registering sensor: {sensor_name}")
                    sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
                    db.session.add(sensor)
                    db.session.commit()

                # ----------------------------
                # Deduplication Logic
                # ----------------------------
                bssid = payload.get("bssid")
                now = time.time()

                if bssid in LAST_SEEN_CACHE:
                    if now - LAST_SEEN_CACHE[bssid] < COOLDOWN:
                        print(f"[SKIP] Duplicate scan ignored for {bssid}")
                        return

                LAST_SEEN_CACHE[bssid] = now

                # ----------------------------
                # Topology Update
                # ----------------------------
                topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
                if not topology:
                    topology = NetworkTopology(
                        sensor_id=sensor.id,
                        discovered_networks=[],
                        discovered_devices=[]
                    )
                    db.session.add(topology)

                current_networks = topology.discovered_networks or []

                network_info = {
                    "ssid": payload.get("ssid"),
                    "bssid": bssid,
                    "channel": payload.get("channel"),
                    "signal": payload.get("signal"),
                    "distance": payload.get("distance"),
                    "auth": payload.get("auth"),
                    "wps": payload.get("wps"),
                    "manufacturer": payload.get("manufacturer"),
                    "uptime": payload.get("uptime"),
                    "raw_beacon": str(payload.get("raw_beacon"))[:200],  # limit size
                    "elapsed_time": payload.get("elapsed_time"),
                    "status": payload.get("status"),
                    "score": payload.get("score"),
                    "last_seen": payload.get("timestamp")
                }

                # update or insert
                found = False
                for i, net in enumerate(current_networks):
                    if net.get("bssid") == bssid:
                        current_networks[i] = network_info
                        found = True
                        break

                if not found:
                    current_networks.append(network_info)

                topology.discovered_networks = current_networks

                # ----------------------------
                # Save History (Controlled)
                # ----------------------------
                severity_map = {
                    "ROGUE": "HIGH",
                    "SUSPICIOUS": "MEDIUM",
                    "LEGIT": "INFO"
                }

                manufacturer = payload.get("manufacturer", "Unknown")
                distance = f"{payload.get('distance', 0)}m"
                channel = payload.get("channel", "??")
                auth = payload.get("auth", "OPEN")

                tidy_description = (
                    f"MFG: {manufacturer:<15} | "
                    f"Dist: {distance:>6} | "
                    f"CH: {channel:>2} | "
                    f"Auth: {auth}"
                )

                history_entry = Threat(
                    threat_type=payload.get("status", "SCAN"),
                    severity=severity_map.get(payload.get("status"), "INFO"),
                    source_mac=bssid,
                    ssid=payload.get("ssid"),
                    detected_by=sensor.id,
                    description=tidy_description
                )

                db.session.add(history_entry)
                db.session.commit()

                print(f"[DB] ✅ Saved scan for {bssid}")

                # ----------------------------
                # Broadcast
                # ----------------------------
                socketio.emit("new_scan_data", payload)

            except Exception as e:
                print(f"[DB-FAILURE] ❌ Error: {e}")
                db.session.rollback()

    return socketio


# --------------------------------
# Broadcast Threat Event
# --------------------------------
def broadcast_threat_event(threat_data):

    socketio = current_app.socketio
    socketio.emit("threat_event", threat_data)

    print("[WebSocket] 📡 Threat broadcasted")


# --------------------------------
# Broadcast Sensor Status
# --------------------------------
def broadcast_sensor_status(sensor_data):

    socketio = current_app.socketio
    socketio.emit("sensor_status", sensor_data)

    print("[WebSocket] 📡 Sensor status broadcasted")