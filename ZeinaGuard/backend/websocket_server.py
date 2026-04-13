"""
WebSocket Server for ZeinaGuard Pro
Handles communication between Sensors and Dashboard
"""

import os
import json
import sys
import traceback
from datetime import datetime
from flask_socketio import SocketIO, emit
from redis import Redis
from flask import request, current_app
from models import db, Threat, ThreatEvent, Sensor, NetworkTopology

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

def get_or_create_sensor(sensor_name):
    """Resolves sensor name to integer ID (Part 1)."""
    sensor = Sensor.query.filter_by(name=sensor_name).first()
    if not sensor:
        try:
            sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
            db.session.add(sensor)
            db.session.commit()
            print(f"[SENSOR] Created new sensor: {sensor_name} (ID={sensor.id})", flush=True)
        except Exception as e:
            db.session.rollback()
            print(f"[ERROR] Could not create sensor: {e}", flush=True)
            return None
    return sensor

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
        sensor_name = data.get("sensor_name", data.get("sensor_id", "unknown"))
        print(f"[WebSocket] 🛰️ Sensor Registered: {sensor_name}")
        emit("registration_success", {"status": "registered", "sensor_name": sensor_name})

    # ----------------------------
    # Receive Threat from Sensor (Part 1, 2, 6)
    # ----------------------------
    @socketio.on("new_threat")
    def handle_new_threat(payload):
        DEBUG_WS = os.getenv("DEBUG_WS", "true").lower() == "true"
        ssid = payload.get('ssid', 'N/A')
        bssid = payload.get('source_mac', 'N/A')
        sensor_name = payload.get('sensor_name', 'unknown')
        
        # [RECEIVED] Log (Part 6)
        print(f"[RECEIVED] SSID={ssid} BSSID={bssid} SENSOR={sensor_name}", flush=True)

        with app.app_context():
            try:
                # Resolve Sensor ID (Part 1)
                sensor = get_or_create_sensor(sensor_name)
                if not sensor:
                    print(f"[DB-FAILURE] ❌ Could not resolve sensor: {sensor_name}", flush=True)
                    return {"status": "error", "message": "Invalid sensor"}
                
                print(f"[SENSOR] Resolved ID = {sensor.id}", flush=True)

                # Validation (Part 2)
                if not isinstance(sensor.id, int):
                    print(f"[DB-FAILURE] ❌ sensor_id is not integer: {sensor.id}", flush=True)
                    return {"status": "error", "message": "Invalid sensor ID type"}

                new_threat = Threat(
                    threat_type=payload.get("threat_type", "UNKNOWN"),
                    severity=payload.get("severity", "HIGH"),
                    source_mac=bssid,
                    ssid=ssid,
                    description=payload.get("description", "Detected via Sensor WebSocket"),
                    detected_by=sensor.id, # Now integer ✅
                    created_by=None
                )

                db.session.add(new_threat)
                db.session.commit()
                
                print(f"[DB-SUCCESS] Inserted threat ID: {new_threat.id}", flush=True)

                socketio.emit("threat_event", {
                    "id": new_threat.id,
                    "type": "threat_detected",
                    "timestamp": datetime.now().isoformat(),
                    "data": payload
                })
                
                return {"status": "ok", "id": new_threat.id}

            except Exception as e:
                db.session.rollback()
                print(f"[DB-FAILURE] Error: {str(e)}", file=sys.stderr, flush=True)
                return {"status": "error", "message": str(e)}

    # ----------------------------
    # Receive Network Scan Data (Part 4, 5, 6)
    # ----------------------------
    @socketio.on("network_scan")
    def handle_network_scan(payload):
        DEBUG_WS = os.getenv("DEBUG_WS", "true").lower() == "true"
        sensor_name = payload.get("sensor_name", "sensor1")
        ssid = payload.get('ssid', 'Unknown SSID')
        bssid = payload.get('bssid', 'N/A')
        status = payload.get("status", "LEGIT")
        
        # [RECEIVED] Log (Part 6)
        print(f"[RECEIVED] SSID={ssid:<15} BSSID={bssid} SENSOR={sensor_name}", flush=True)
        
        with app.app_context():
            try:
                # 1. Resolve Sensor
                sensor = get_or_create_sensor(sensor_name)
                if not sensor: return {"status": "error"}
                print(f"[SENSOR] Resolved ID = {sensor.id}", flush=True)

                # 2. Topology Update (UPSERT - Part 5)
                topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
                if not topology:
                    topology = NetworkTopology(sensor_id=sensor.id, discovered_networks=[], discovered_devices=[])
                    db.session.add(topology)
                
                current_networks = topology.discovered_networks or []
                if isinstance(current_networks, str):
                    try: current_networks = json.loads(current_networks)
                    except: current_networks = []
                
                network_info = {
                    "ssid": ssid, "bssid": bssid, "channel": payload.get("channel"),
                    "signal": payload.get("signal"), "distance": payload.get("distance"),
                    "auth": payload.get("auth"), "wps": payload.get("wps"),
                    "manufacturer": payload.get("manufacturer"), "uptime": payload.get("uptime"),
                    "status": status, "score": payload.get("score"),
                    "last_seen": payload.get("timestamp"), "clients": payload.get("clients", [])
                }

                found = False
                for i, net in enumerate(current_networks):
                    if isinstance(net, dict) and net.get("bssid") == bssid:
                        current_networks[i] = network_info
                        found = True
                        break
                if not found: current_networks.append(network_info)
                
                topology.discovered_networks = current_networks
                
                # 3. Conditional Threat Creation (Part 4)
                # Only insert into threats table if status is ROGUE or SUSPICIOUS
                if status in ["ROGUE", "SUSPICIOUS"]:
                    severity_map = {"ROGUE": "HIGH", "SUSPICIOUS": "MEDIUM"}
                    history_entry = Threat(
                        threat_type=status,
                        severity=severity_map.get(status, "MEDIUM"),
                        source_mac=bssid,
                        ssid=ssid,
                        detected_by=sensor.id, # Integer ✅
                        description=f"Scan Alert | CH: {payload.get('channel')} | Score: {payload.get('score')}",
                        created_by=None
                    )
                    db.session.add(history_entry)
                    print(f"[DB-SUCCESS] Inserted {status} threat for {bssid}", flush=True)
                else:
                    if DEBUG_WS: print(f"[INFO] Skipping threat insert for LEGIT network {bssid}", flush=True)

                db.session.commit()
                socketio.emit("new_scan_data", payload)
                return {"status": "ok"}

            except Exception as e:
                db.session.rollback()
                print(f"[DB-FAILURE] Error: {str(e)}", file=sys.stderr, flush=True)
                return {"status": "error", "message": str(e)}

    return socketio

def broadcast_threat_event(threat_data):
    socketio = current_app.socketio
    socketio.emit("threat_event", threat_data)
    print("[WebSocket] 📡 Threat broadcasted")

def broadcast_sensor_status(sensor_data):
    socketio = current_app.socketio
    socketio.emit("sensor_status", sensor_data)
    print("[WebSocket] 📡 Sensor status broadcasted")
