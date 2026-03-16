"""
WebSocket Server for ZeinaGuard Pro
"""
import os
import json
from datetime import datetime
from flask_socketio import SocketIO, emit
from redis import Redis
from flask import request, current_app
from models import db, Threat, ThreatEvent, Sensor

# Redis connection
try:
    redis_client = Redis.from_url(os.getenv('REDIS_URL', 'redis://localhost:6379/0'), decode_responses=True)
except:
    redis_client = None

connected_clients = {}

def init_socketio(app):
    socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

    @socketio.on('connect')
    def handle_connect():
        client_id = request.sid
        connected_clients[client_id] = {'connected_at': datetime.now().isoformat()}
        print(f"[WebSocket] 🟢 Client Connected: {client_id}")

    # --- المهم: استقبال التهديدات من السنسور ---
    @socketio.on('new_threat')
    def handle_new_threat(payload):
        """ يستقبل التهديد من السنسور، يحفظه في الداتا بيز، ويبعت للداشبورد """
        print(f"[WebSocket] 🚨 Received Threat: {payload.get('ssid')} from Sensor")
        
        with app.app_context():
            try:
                # 1. حفظ التهديد في قاعدة البيانات
                new_threat = Threat(
                    threat_type=payload.get('threat_type', 'UNKNOWN'),
                    severity=payload.get('severity', 'HIGH'),
                    source_mac=payload.get('source_mac'),
                    ssid=payload.get('ssid'),
                    description=f"Detected via Sensor WebSocket"
                )
                db.session.add(new_threat)
                db.session.commit()

                # 2. تجهيز البيانات للإرسال للـ Frontend (React/Next.js)
                broadcast_data = {
                    "id": new_threat.id,
                    "type": "threat_detected",
                    "timestamp": datetime.now().isoformat(),
                    "data": payload
                }

                # 3. إرسال (Broadcast) لكل المفتوح عندهم الداشبورد
                socketio.emit('threat_event', broadcast_data)
                print(f"[WebSocket] 🚀 Broadcasted to Dashboard: {new_threat.id}")

            except Exception as e:
                db.session.rollback()
                print(f"[WebSocket] ❌ Error saving threat: {e}")

    @socketio.on('sensor_register')
    def handle_sensor_register(data):
        print(f"[WebSocket] 🛰️ Sensor Registered: {data.get('sensor_id')}")
        emit('registration_success', {"status": "registered"})

    return socketio

# الدالة دي بتستخدم لو حبيت تبعت حاجة من الـ Routes العادية
def broadcast_threat_event(threat_data):
    from flask import current_app
    socketio = current_app.socketio
    socketio.emit('threat_event', threat_data)