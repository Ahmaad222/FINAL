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
from sqlalchemy.orm.attributes import flag_modified
from models import db, Threat, Sensor, NetworkTopology

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
# State & Caching
# --------------------------------
connected_clients = {}
LAST_SEEN_CACHE = {}
COOLDOWN = 60  # seconds
cache_lock = threading.Lock()  # Thread-safe lock for dictionary

# --------------------------------
# Cache Cleanup Thread
# --------------------------------
def cleanup_cache():
    while True:
        now = time.time()
        with cache_lock:
            # Safely identify keys to remove without altering dict during iteration
            expired_keys = [bssid for bssid, timestamp in LAST_SEEN_CACHE.items() if now - timestamp > 120]
            for bssid in expired_keys:
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
    # Receive New Threat
    # ----------------------------
    @socketio.on("new_threat")
    def handle_new_threat(payload):
        # Listener for the "new_threat" event emitted by the client
        print(f"[WebSocket] 🚨 New Threat Received: {payload.get('threat_type')} from {payload.get('source_mac')}")
        # Broadcast to dashboard clients
        socketio.emit("threat_event", payload, broadcast=True)

    # ----------------------------
    # Receive Network Scan Data
    # ----------------------------
    @socketio.on("network_scan")
    def handle_network_scan(payload):
        sensor_name = payload.get("sensor_id", "sensor1")
        bssid = payload.get("bssid")
        
        print(f"[RECEIVED] SSID={payload.get('ssid')} BSSID={bssid} SENSOR={sensor_name}")

        with current_app.app_context():  # Replaced app with current_app
            try:
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
                now = time.time()
                with cache_lock:
                    if bssid in LAST_SEEN_CACHE and (now - LAST_SEEN_CACHE[bssid] < COOLDOWN):
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

                # Explicitly re-assign and flag as modified for SQLAlchemy JSON columns
                topology.discovered_networks = current_networks
                flag_modified(topology, "discovered_networks")

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
                socketio.emit("new_scan_data", payload, broadcast=True)

            except Exception as e:
                print(f"[DB-FAILURE] ❌ Error: {e}")
                db.session.rollback()

    return socketio

# --------------------------------
# Broadcast Threat Event
# --------------------------------
def broadcast_threat_event(threat_data):
    # Depending on how the app is structured, pulling socketio from extensions is safer 
    # if it's called outside the socketio context.
    socketio = current_app.extensions.get('socketio') or current_app.socketio
    socketio.emit("threat_event", threat_data, broadcast=True)
    print("[WebSocket] 📡 Threat broadcasted")

# --------------------------------
# Broadcast Sensor Status
# --------------------------------
def broadcast_sensor_status(sensor_data):
    socketio = current_app.extensions.get('socketio') or current_app.socketio
    socketio.emit("sensor_status", sensor_data, broadcast=True)
    print("[WebSocket] 📡 Sensor status broadcasted")