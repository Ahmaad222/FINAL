import socketio
import threading
import time
from core.event_bus import dashboard_queue

class WSClient:
    def __init__(self, backend_url=None, token=None):
        self.backend_url = backend_url or "http://192.168.201.130:8000"
        self.token = token

        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=3
        )

        self.is_running = False
        self.thread = None

        # -----------------------------
        # Socket Events
        # -----------------------------
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)
        self.sio.on("connect_error", self._on_connect_error)
        self.sio.on("registration_success", self._on_registration_success)

    def _on_connect(self):
        print(f"[WebSocket] 🟢 Connected to Backend at {self.backend_url}")
        self.sio.emit("sensor_register", {
            "sensor_id": "sensor1"
        })

    def _on_disconnect(self):
        print("[WebSocket] 🔴 Disconnected from server")

    def _on_connect_error(self, data):
        print(f"[WebSocket] ❌ Connection failed: {data}")

    def _on_registration_success(self, data):
        print(f"[WebSocket] ✅ Sensor registered: {data}")

    def connect_to_server(self):
        if not self.token:
            print("[WebSocket] ❌ Cannot start WS without token")
            return

        self.is_running = True
        
        # Start listener thread before blocking with connect loop
        self.thread = threading.Thread(
            target=self._threat_listener,
            daemon=True
        )
        self.thread.start()

        while self.is_running:
            try:
                print(f"[WebSocket] Connecting to {self.backend_url}...")
                self.sio.connect(
                    self.backend_url,
                    headers={
                        "Authorization": f"Bearer {self.token}"
                    },
                    transports=["websocket"]
                )
                self.sio.wait()
                break  # If wait finishes gracefully, break loop

            except Exception as e:
                print(f"[WebSocket] ❌ Connection Error: {e}")
                print("[WebSocket] 🔄 Retrying in 5 seconds...")
                time.sleep(5)

    def stop(self):
        """Gracefully stop the client and the listener thread."""
        self.is_running = False
        if self.sio.connected:
            self.sio.disconnect()

    def _threat_listener(self):
        while self.is_running:
            try:
                # Add timeout to avoid blocking indefinitely, allowing clean shutdown
                # If you import standard queue, you can catch queue.Empty
                data = dashboard_queue.get(timeout=1)

                if not data or not self.sio.connected:
                    continue

                # 🚀 Handle Enriched Network Scan Data
                if data.get("type") == "NETWORK_SCAN":
                    event = data.get("event", {})
                    payload = {
                        "sensor_id": "sensor1",
                        "ssid": event.get("ssid"),
                        "bssid": event.get("bssid"),
                        "channel": event.get("channel"),
                        "signal": event.get("signal"),
                        "distance": event.get("distance"),
                        "auth": event.get("auth"),
                        "wps": event.get("wps"),
                        "manufacturer": event.get("manufacturer"),
                        "uptime": event.get("uptime"),
                        "raw_beacon": event.get("raw_beacon"),
                        "elapsed_time": event.get("elapsed_time"),
                        "timestamp": event.get("timestamp"),
                        "status": data.get("status"),
                        "score": data.get("score")
                    }
                    self.sio.emit("network_scan", payload)
                    print(f"[WebSocket] 📡 Network Data Sent: {payload['ssid']} ({payload['bssid']})")
                    continue

                # 🛑 Existing Threat Logic
                event = data.get("event", {})
                payload = {
                    "threat_type": data.get("status"),
                    "ssid": event.get("ssid"),
                    "source_mac": event.get("bssid"),
                    "signal": event.get("signal"),
                    "severity": "HIGH"
                }

                self.sio.emit("new_threat", payload)
                print(f"[WebSocket] 🚀 Threat Sent: {payload.get('ssid', 'Unknown')}")

            except Exception as e:
                # Expected when queue is empty during timeout
                pass

            time.sleep(0.1)