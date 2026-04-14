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
# State & Caching
# --------------------------------
connected_clients = {}
LAST_SEEN_CACHE = {}
COOLDOWN = 60  
cache_lock = threading.Lock()

def cleanup_cache():
    while True:
        now = time.time()
        with cache_lock:
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

    @socketio.on("connect")
    def handle_connect():
        client_id = request.sid
        connected_clients[client_id] = {"connected_at": datetime.now().isoformat()}
        print(f"[WebSocket] 🟢 Client Connected: {client_id}")

    @socketio.on("disconnect")
    def handle_disconnect():
        client_id = request.sid
        if client_id in connected_clients:
            del connected_clients[client_id]
        print(f"[WebSocket] 🔴 Client Disconnected: {client_id}")

    @socketio.on("sensor_register")
    def handle_sensor_register(data):
        sensor_id = data.get("sensor_id")
        print(f"[WebSocket] 🛰️ Sensor Registered: {sensor_id}")
        emit("registration_success", {"status": "registered", "sensor_id": sensor_id})

    # ----------------------------
    # تم تعديل هذا الجزء (حذف broadcast=True)
    # ----------------------------
    @socketio.on("new_threat")
    def handle_new_threat(payload):
        print(f"[WebSocket] 🚨 New Threat Received: {payload.get('threat_type')}")
        # في Flask-SocketIO، الـ emit العادية داخل handler بتبعت لكل المتصلين (Broadcast) تلقائياً
        socketio.emit("threat_event", payload) 

    @socketio.on("network_scan")
    def handle_network_scan(payload):
        sensor_name = payload.get("sensor_id", "sensor1")
        bssid = payload.get("bssid")
        
        with current_app.app_context():
            try:
                sensor = Sensor.query.filter_by(name=sensor_name).first()
                if not sensor:
                    sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
                    db.session.add(sensor)
                    db.session.commit()

                now = time.time()
                with cache_lock:
                    if bssid in LAST_SEEN_CACHE and (now - LAST_SEEN_CACHE[bssid] < COOLDOWN):
                        return
                    LAST_SEEN_CACHE[bssid] = now

                topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
                if not topology:
                    topology = NetworkTopology(sensor_id=sensor.id, discovered_networks=[])
                    db.session.add(topology)

                current_networks = topology.discovered_networks or []
                
                network_info = {
                    "ssid": payload.get("ssid"),
                    "bssid": bssid,
                    "channel": payload.get("channel"),
                    "signal": payload.get("signal"),
                    "status": payload.get("status"),
                    "last_seen": payload.get("timestamp")
                }

                found = False
                for i, net in enumerate(current_networks):
                    if net.get("bssid") == bssid:
                        current_networks[i] = network_info
                        found = True
                        break
                if not found:
                    current_networks.append(network_info)

                topology.discovered_networks = current_networks
                flag_modified(topology, "discovered_networks")

                # حفظ التهديد في القاعدة
                history_entry = Threat(
                    threat_type=payload.get("status", "SCAN"),
                    severity="HIGH" if payload.get("status") == "ROGUE" else "INFO",
                    source_mac=bssid,
                    ssid=payload.get("ssid"),
                    detected_by=sensor.id
                )
                db.session.add(history_entry)
                db.session.commit()

                # تم تعديل هذا الجزء (حذف broadcast=True)
                socketio.emit("new_scan_data", payload)

            except Exception as e:
                print(f"[DB-FAILURE] ❌ Error: {e}")
                db.session.rollback()

    return socketio