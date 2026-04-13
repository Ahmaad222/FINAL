import socketio
import threading
import time

from core.event_bus import dashboard_queue


class WSClient:

    def __init__(self, backend_url=None, token=None, sensor_name="sensor1"):

        self.backend_url = backend_url or "http://127.0.0.1:5000"
        self.token = token
        self.sensor_name = sensor_name

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
            print(f"[WebSocket] 🟢 Connected to Backend at {self.backend_url}")

            self.sio.emit("sensor_register", {
                "sensor_name": self.sensor_name
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

        while True:
            try:
                print(f"[WebSocket] Connecting to {self.backend_url}...")

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
                break 

            except Exception as e:
                print(f"[WebSocket] ❌ Connection Error: {e}")
                print("[WebSocket] 🔄 Retrying in 5 seconds...")
                time.sleep(5)

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
                        "sensor_name": self.sensor_name, # Part 7
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
                        "fingerprint": event.get("fingerprint"),
                        "elapsed_time": event.get("elapsed_time"),
                        "timestamp": event.get("timestamp"),
                        "status": data.get("status"),
                        "score": data.get("score"),
                        "clients": event.get("clients", [])
                    }
                    
                    print(f"[WS] Sent Scan → backend: SSID={payload['ssid']} BSSID={payload['bssid']}")
                    self.sio.emit("network_scan", payload, callback=self._ack_callback)
                    continue

                # 🛑 Existing Threat Logic
                event = data.get("event", {})

                payload = {
                    "threat_type": data.get("status"),
                    "ssid": event.get("ssid"),
                    "source_mac": event.get("bssid"),
                    "signal": event.get("signal"),
                    "severity": "HIGH",
                    "sensor_name": self.sensor_name # Part 7
                }

                print(f"[WS] Sending Threat → backend: {payload['ssid']}")
                self.sio.emit("new_threat", payload, callback=self._ack_callback)

            except Exception as e:
                print(f"[WebSocket] Listener Error: {e}")

            time.sleep(0.1)

    def _ack_callback(self, data=None):
        print(f"[WS] ACK received from backend")
