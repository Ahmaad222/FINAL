import socketio
import threading
import time

from core.event_bus import dashboard_queue


class WSClient:

    def __init__(self, backend_url="http://192.168.201.130:5001", token=None):

        self.backend_url = backend_url
        self.token = token

        self.sio = socketio.Client(
            logger=False,
            engineio_logger=False,
            reconnection=True,
            reconnection_attempts=10,
            reconnection_delay=3
        )

        self.is_running = False

        # ------------------

        @self.sio.event
        def connect():

            print("\n[WebSocket] 🟢 Connected to ZeinaGuard!")

            # Register Sensor
            self.sio.emit("sensor_register", {
                "sensor_id": "sensor1",
                "name": "ZeinaGuard Sensor"
            })

        @self.sio.event
        def disconnect():

            print("\n[WebSocket] 🔴 Disconnected from server")

        @self.sio.event
        def threat_event(data):

            print(f"\n[Dashboard] Threat Event: {data}")

    # ======================

    def connect_to_server(self):

        if not self.token:

            print("[WebSocket] Cannot connect without JWT Token")
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

            listener = threading.Thread(
                target=self._threat_listener,
                daemon=True
            )

            listener.start()

            self.sio.wait()

        except Exception as e:

            print(f"[WebSocket] Connection Error: {e}")

    # ======================

    def _threat_listener(self):

        print("[WebSocket] Listening for threats...")

        last_threat_id = None

        while self.is_running:

            threat = dashboard_queue.get()

            event_data = threat.get("event", {}) if isinstance(threat, dict) else {}

            ssid = event_data.get("ssid", "Hidden")
            mac = event_data.get("bssid", "Unknown_MAC")
            threat_type = threat.get("status", "UNKNOWN")

            threat_id = f"{ssid}_{mac}_{threat_type}"

            if threat_id == last_threat_id:
                continue

            if not self.sio.connected:
                continue

            try:

                payload = {

                    "threat_type": threat_type,
                    "ssid": ssid,
                    "source_mac": mac,
                    "signal": event_data.get("signal", -100),
                    "timestamp": event_data.get("timestamp"),
                    "severity": "HIGH" if threat_type == "ROGUE" else "MEDIUM"

                }

                self.sio.emit("new_threat", payload)

                print(f"[WebSocket] 🚀 Threat sent: {ssid}")

                last_threat_id = threat_id

            except Exception as e:

                print(f"[WebSocket] Failed to send threat: {e}")

            time.sleep(0.05)

    # ======================

    def disconnect_server(self):

        self.is_running = False
        self.sio.disconnect()
