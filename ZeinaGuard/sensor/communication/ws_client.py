import socketio
import threading
import time

from core.event_bus import dashboard_queue


class WSClient:

    def __init__(self, backend_url="http://192.168.201.130:8000", token=None):

        self.backend_url = backend_url
        self.token = token

        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=3
        )

        self.is_running = False

        # -----------------------------
        # Socket Events
        # -----------------------------

        @self.sio.event
        def connect():
            print("[WebSocket] 🟢 Connected to Backend")

            self.sio.emit("sensor_register", {
                "sensor_id": "sensor1"
            })

        @self.sio.event
        def disconnect():
            print("[WebSocket] 🔴 Disconnected from server")

        @self.sio.event
        def connect_error(data):
            print(f"[WebSocket] ❌ Connection failed: {data}")

        @self.sio.on("registration_success")
        def registration_success(data):
            print(f"[WebSocket] ✅ Sensor registered: {data}")

    def connect_to_server(self):

        if not self.token:
            print("[WebSocket] ❌ Cannot start WS without token")
            return

        try:

            print("[WebSocket] Connecting to server...")

            self.sio.connect(
                self.backend_url,
                headers={
                    "Authorization": f"Bearer {self.token}"
                },
                transports=["websocket"]
            )

            self.is_running = True

            threading.Thread(
                target=self._threat_listener,
                daemon=True
            ).start()

            self.sio.wait()

        except Exception as e:
            print(f"[WebSocket] ❌ Connection Error: {e}")

    def _threat_listener(self):

        while self.is_running:

            try:

                data = dashboard_queue.get()

                if not data:
                    continue

                if not self.sio.connected:
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
                        "timestamp": event.get("timestamp"),
                        "status": data.get("status"),
                        "score": data.get("score")
                    }
                    self.sio.emit("network_scan", payload)
                    # print(f"[WebSocket] 📡 Network Data Sent: {payload['ssid']}")
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

                print(f"[WebSocket] 🚀 Threat Sent: {payload['ssid']}")

            except Exception as e:
                print(f"[WebSocket] Listener Error: {e}")

            time.sleep(0.1)