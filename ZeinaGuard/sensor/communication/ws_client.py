import socketio
import threading
import time
from core.event_bus import dashboard_queue

class WSClient:
    def __init__(self, backend_url="http://192.168.201.130:8000", token=None):
        self.backend_url = backend_url
        self.token = token
        self.sio = socketio.Client(reconnection=True, reconnection_delay=3)
        self.is_running = False

        @self.sio.event
        def connect():
            print("\n[WebSocket] 🟢 Connected to Backend!")
            self.sio.emit("sensor_register", {"sensor_id": "sensor1"})

    def connect_to_server(self):
        if not self.token: return
        try:
            self.sio.connect(self.backend_url, headers={"Authorization": f"Bearer {self.token}"}, transports=["websocket"])
            self.is_running = True
            threading.Thread(target=self._threat_listener, daemon=True).start()
            self.sio.wait()
        except Exception as e:
            print(f"[WebSocket] ❌ Connection Error: {e}")

    def _threat_listener(self):
        while self.is_running:
            try:
                threat = dashboard_queue.get() # يسحب من الـ ThreatManager
                if self.sio.connected:
                    event_data = threat.get("event", {})
                    payload = {
                        "threat_type": threat.get("status"),
                        "ssid": event_data.get("ssid"),
                        "source_mac": event_data.get("bssid"),
                        "severity": "HIGH",
                        "signal": event_data.get("signal")
                    }
                    self.sio.emit("new_threat", payload) # بيبعت للسيرفر
                    print(f"[WebSocket] 🚀 Sent: {payload['ssid']}")
            except: pass
            time.sleep(0.1)