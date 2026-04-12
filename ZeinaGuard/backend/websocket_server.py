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
        import traceback
        import sys
        
        DEBUG_WS = os.getenv("DEBUG_WS", "true").lower() == "true"
        ssid = payload.get('ssid', 'N/A')
        sensor_id = payload.get('sensor_id', 'unknown')
        
        if DEBUG_WS:
            print(f"[RECEIVED] 🚨 THREAT | SSID={ssid} | TYPE={payload.get('threat_type')} | SENSOR={sensor_id}", flush=True)

        with app.app_context():
            try:
                new_threat = Threat(
                    threat_type=payload.get("threat_type", "UNKNOWN"),
                    severity=payload.get("severity", "HIGH"),
                    source_mac=payload.get("source_mac"),
                    ssid=payload.get("ssid"),
                    description=payload.get("description", "Detected via Sensor WebSocket"),
                    detected_by=payload.get("sensor_id"),
                    created_by=None
                )

                db.session.add(new_threat)
                db.session.commit()
                
                if DEBUG_WS:
                    print(f"[DB-SUCCESS] ✅ Threat saved ID: {new_threat.id}", flush=True)

                broadcast_data = {
                    "id": new_threat.id,
                    "type": "threat_detected",
                    "timestamp": datetime.now().isoformat(),
                    "data": payload
                }
                socketio.emit("threat_event", broadcast_data)

            except Exception as e:
                db.session.rollback()
                print(f"[DB-FAILURE] ❌ Error saving threat: {str(e)}", file=sys.stderr, flush=True)
                traceback.print_exc()

    # ----------------------------
    # Receive Network Scan Data
    # ----------------------------
    @socketio.on("network_scan")
    def handle_network_scan(payload):
        """Processes enriched network data from sensor."""
        import traceback
        import json
        import sys
        
        DEBUG_WS = os.getenv("DEBUG_WS", "true").lower() == "true"
        sensor_name = payload.get("sensor_id", "sensor1")
        ssid = payload.get('ssid', 'Unknown SSID')
        bssid = payload.get('bssid', 'N/A')
        signal = payload.get('signal', '??')
        
        if DEBUG_WS:
            print(f"[RECEIVED] 📡 SCAN | SSID={ssid:<15} | BSSID={bssid} | SIG={signal:>3} | SENSOR={sensor_name}", flush=True)
        
        with app.app_context():
            try:
                from models import NetworkTopology, Sensor, db
                
                # 🛠️ Find or Auto-Create the sensor
                sensor = Sensor.query.filter_by(name=sensor_name).first()
                if not sensor:
                    sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
                    db.session.add(sensor)
                    db.session.commit()
                    if DEBUG_WS: print(f"[DB] Created sensor: {sensor_name}", flush=True)
                
                # 🛠️ Find or Create the topology record
                topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
                if not topology:
                    topology = NetworkTopology(sensor_id=sensor.id, discovered_networks=[], discovered_devices=[])
                    db.session.add(topology)
                
                # 🛠️ Fix: Ensure discovered_networks is a list
                current_networks = topology.discovered_networks
                if isinstance(current_networks, str):
                    try:
                        current_networks = json.loads(current_networks)
                    except:
                        current_networks = []
                
                if current_networks is None:
                    current_networks = []
                
                # Update topology with latest scan
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

                found = False
                for i, net in enumerate(current_networks):
                    if isinstance(net, dict) and net.get("bssid") == bssid:
                        current_networks[i] = network_info
                        found = True
                        break
                
                if not found:
                    current_networks.append(network_info)
                
                topology.discovered_networks = current_networks
                
                # 🛠️ Save to history (Threat table)
                severity_map = {"ROGUE": "HIGH", "SUSPICIOUS": "MEDIUM", "LEGIT": "INFO"}
                
                history_entry = Threat(
                    threat_type=payload.get("status", "SCAN"),
                    severity=severity_map.get(payload.get("status"), "INFO"),
                    source_mac=bssid,
                    ssid=ssid,
                    detected_by=sensor.id,
                    description=f"CH: {payload.get('channel')} | Auth: {payload.get('auth')}",
                    created_by=None
                )
                db.session.add(history_entry)
                
                db.session.commit()
                if DEBUG_WS: print(f"[DB-SUCCESS] ✅ Scan data saved", flush=True)
                
                # Broadcast to UI
                socketio.emit("new_scan_data", payload)
                
            except Exception as e:
                db.session.rollback()
                print(f"[DB-FAILURE] ❌ Error processing scan data: {str(e)}", file=sys.stderr, flush=True)
                traceback.print_exc()


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