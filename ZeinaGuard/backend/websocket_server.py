"""
WebSocket Server for ZeinaGuard Pro
Handles communication between Sensors and Dashboard
"""

import os
import time
import threading
from datetime import datetime
from flask_socketio import SocketIO, emit
from flask import request, current_app
from sqlalchemy.orm.attributes import flag_modified
from models import db, Threat, Sensor, NetworkTopology

# ---------------------------------------------------------
# 1. إعدادات الكاش لمنع تكرار البيانات (Deduplication)
# ---------------------------------------------------------
LAST_SEEN_CACHE = {}
COOLDOWN = 60  # ثانية: المدة التي يتم فيها تجاهل نفس الـ BSSID
cache_lock = threading.Lock()

def cleanup_cache():
    """خيط منفصل يقوم بتنظيف الكاش القديم لتوفير الذاكرة"""
    while True:
        now = time.time()
        with cache_lock:
            # حذف العناصر التي مر عليها أكثر من دقيقتين
            expired_keys = [k for k, v in LAST_SEEN_CACHE.items() if now - v > 120]
            for k in expired_keys:
                del LAST_SEEN_CACHE[k]
        time.sleep(30)

# تشغيل خيط التنظيف فور تشغيل الملف
threading.Thread(target=cleanup_cache, daemon=True).start()

# ---------------------------------------------------------
# 2. تهيئة SocketIO والتعامل مع الأحداث
# ---------------------------------------------------------
def init_socketio(app):
    """تهيئة Flask-SocketIO وربط الأحداث"""
    
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading"
    )

    @socketio.on("connect")
    def handle_connect():
        print(f"[WebSocket] 🟢 Client Connected: {request.sid}")

    @socketio.on("disconnect")
    def handle_disconnect():
        print(f"[WebSocket] 🔴 Client Disconnected: {request.sid}")

    @socketio.on("sensor_register")
    def handle_sensor_register(data):
        """تسجيل السنسور عند بدء اتصاله"""
        sensor_id = data.get("sensor_id", "unknown_sensor")
        print(f"[WebSocket] 🛰️ Sensor Registered: {sensor_id}")
        emit("registration_success", {"status": "registered", "sensor_id": sensor_id})

    @socketio.on("new_threat")
    def handle_new_threat(payload):
        """استقبال تهديد مباشر من السنسور وبثه للـ Dashboard"""
        print(f"[WebSocket] 🚨 New Threat Received: {payload.get('threat_type')}")
        # ملاحظة: في Flask-SocketIO، emit بدون تحديد sid تقوم بعمل broadcast تلقائي
        socketio.emit("threat_event", payload)

    @socketio.on("network_scan")
    def handle_network_scan(payload):
        """معالجة نتائج فحص الشبكة، تخزينها في DB، وبثها"""
        sensor_name = payload.get("sensor_id", "sensor1")
        bssid = payload.get("bssid")
        
        # استخدام context التطبيق للتعامل مع SQLAlchemy بأمان داخل الـ Threads
        with current_app.app_context():
            try:
                # أ. التحقق من وجود السنسور أو إنشاؤه تلقائياً
                sensor = Sensor.query.filter_by(name=sensor_name).first()
                if not sensor:
                    print(f"[WebSocket] 🆕 Auto-registering sensor in DB: {sensor_name}")
                    sensor = Sensor(name=sensor_name, hostname=sensor_name, is_active=True)
                    db.session.add(sensor)
                    db.session.commit()

                # ب. منع التكرار (Deduplication)
                now = time.time()
                with cache_lock:
                    if bssid in LAST_SEEN_CACHE and (now - LAST_SEEN_CACHE[bssid] < COOLDOWN):
                        print(f"[WebSocket] ⏩ Skipping duplicate scan for {bssid}")
                        return
                    LAST_SEEN_CACHE[bssid] = now

                # ج. تحديث توبولوجيا الشبكة (Topology)
                topology = NetworkTopology.query.filter_by(sensor_id=sensor.id).first()
                if not topology:
                    topology = NetworkTopology(sensor_id=sensor.id, discovered_networks=[])
                    db.session.add(topology)

                networks = topology.discovered_networks or []
                network_info = {
                    "ssid": payload.get("ssid"),
                    "bssid": bssid,
                    "channel": payload.get("channel"),
                    "signal": payload.get("signal"),
                    "status": payload.get("status"),
                    "last_seen": payload.get("timestamp")
                }

                # تحديث بيانات الشبكة إذا كانت موجودة مسبقاً أو إضافتها
                updated = False
                for i, net in enumerate(networks):
                    if net.get("bssid") == bssid:
                        networks[i] = network_info
                        updated = True
                        break
                
                if not updated:
                    networks.append(network_info)

                # إخبار SQLAlchemy أن الـ JSON قد تغير ليتم حفظه
                topology.discovered_networks = networks
                flag_modified(topology, "discovered_networks")

                # د. تسجيل الحدث في سجل التهديدات (Threats History)
                history_entry = Threat(
                    threat_type=payload.get("status", "SCAN"),
                    severity="HIGH" if payload.get("status") == "ROGUE" else "INFO",
                    source_mac=bssid,
                    ssid=payload.get("ssid"),
                    detected_by=sensor.id,
                    description=f"Scan result from {sensor_name} | Signal: {payload.get('signal')}"
                )
                db.session.add(history_entry)
                db.session.commit()

                # هـ. بث البيانات للـ Dashboard
                socketio.emit("new_scan_data", payload)
                print(f"[DB] ✅ Data saved and broadcasted for {bssid}")

            except Exception as e:
                print(f"[WebSocket ERROR] ❌: {str(e)}")
                db.session.rollback()

    return socketio

# ---------------------------------------------------------
# 3. دوال البث العامة (للاستخدام من خارج الـ Socket context)
# ---------------------------------------------------------
def broadcast_threat_event(threat_data):
    """إرسال تنبيه تهديد للـ Dashboard من أي مكان في التطبيق"""
    # البحث عن الـ socketio في سياق التطبيق الحالي
    socketio = current_app.extensions.get('socketio')
    if socketio:
        socketio.emit("threat_event", threat_data)
        print("[WebSocket] 📡 Global Threat Broadcasted")

def broadcast_sensor_status(sensor_data):
    """تحديث حالة السنسور (Online/Offline) على الواجهة"""
    socketio = current_app.extensions.get('socketio')
    if socketio:
        socketio.emit("sensor_status", sensor_data)