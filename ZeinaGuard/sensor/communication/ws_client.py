import os
import socket
import threading
import time
from datetime import datetime
from queue import Empty

import socketio

from core.event_bus import dashboard_queue, scan_queue
from local_data_logger import LocalDataLogger
from ui.terminal_ui import mark_sent, update_status


RUN_MODE = os.getenv("RUN_MODE", "LOCAL")
if RUN_MODE == "DOCKER":
    DEFAULT_BACKEND_URL = "http://flask-backend:5000"
else:
    DEFAULT_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")

SCAN_EMIT_BATCH_SIZE = int(os.getenv("SCAN_EMIT_BATCH_SIZE", "25"))
SCAN_EMIT_INTERVAL_SECONDS = float(os.getenv("SCAN_EMIT_INTERVAL_SECONDS", "3.0"))
SCAN_DEDUP_SIGNAL_DELTA = int(os.getenv("SCAN_DEDUP_SIGNAL_DELTA", "5"))
SCAN_DEDUP_MAX_AGE_SECONDS = float(os.getenv("SCAN_DEDUP_MAX_AGE_SECONDS", "30"))


class WSClient:
    def __init__(self, backend_url=None, token=None, sensor_id=None):
        self.backend_url = backend_url or DEFAULT_BACKEND_URL
        self.token = token
        self.hostname = socket.gethostname()
        self.sensor_id = sensor_id or os.getenv("ZEINAGUARD_SENSOR_ID", self.hostname)
        self.started_at = time.time()
        self.is_running = False
        self.last_sent_cache = {}
        self.send_buffer = []

        self.local_logger = LocalDataLogger()
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=0,
            reconnection_delay=3,
            logger=False,
            engineio_logger=False,
        )

        self._register_handlers()

    def _register_handlers(self):
        @self.sio.event
        def connect():
            update_status(backend_status="connected", message=f"Connected to {self.backend_url}")
            self.sio.emit(
                "sensor_register",
                {
                    "sensor_id": self.sensor_id,
                    "hostname": self.hostname,
                },
            )

        @self.sio.event
        def disconnect():
            update_status(backend_status="disconnected", message="Backend connection lost")

        @self.sio.event
        def connect_error(_data):
            update_status(backend_status="offline", message="Backend connect failed")

        @self.sio.on("registration_success")
        def registration_success(_data):
            update_status(backend_status="registered", message="Sensor registered")

    def start(self):
        self.is_running = True

        threading.Thread(target=self._scan_listener, daemon=True, name="WSScanListener").start()
        threading.Thread(target=self._threat_listener, daemon=True, name="WSThreatListener").start()

        if not self.token:
            update_status(backend_status="offline", message="Offline mode: local logging only")
            while self.is_running:
                time.sleep(1)
            return

        while self.is_running:
            if self.sio.connected:
                time.sleep(1)
                continue

            try:
                update_status(backend_status="connecting", message=f"Connecting to {self.backend_url}")
                self.sio.connect(
                    self.backend_url,
                    headers={"Authorization": f"Bearer {self.token}"},
                    transports=["websocket"],
                    wait=True,
                )
                self.sio.wait()
            except Exception:
                update_status(backend_status="offline", message="Retrying backend connection")
                time.sleep(5)

    def _threat_listener(self):
        while self.is_running:
            try:
                threat = dashboard_queue.get(timeout=0.5)
            except Empty:
                continue

            if not threat or threat.get("type") == "REMOVED" or not self.sio.connected:
                continue

            event = threat.get("event", {})
            payload = {
                "threat_type": threat.get("status"),
                "ssid": event.get("ssid"),
                "source_mac": event.get("bssid"),
                "signal": event.get("signal"),
                "severity": "HIGH",
            }

            try:
                self.sio.emit("new_threat", payload)
            except Exception:
                update_status(backend_status="degraded", message="Threat send failed")

    def _scan_listener(self):
        next_flush_deadline = time.monotonic() + SCAN_EMIT_INTERVAL_SECONDS

        while self.is_running:
            try:
                timeout = max(0.1, next_flush_deadline - time.monotonic())
                scan = scan_queue.get(timeout=timeout)
            except Empty:
                scan = None

            if scan is not None:
                if not self._should_process_scan(scan):
                    continue

                payload = self._build_scan_payload(scan)
                self.local_logger.log_scan(payload)
                self.send_buffer.append(payload)
                self._update_last_sent_cache(payload)

            should_flush = (
                len(self.send_buffer) >= SCAN_EMIT_BATCH_SIZE
                or (self.send_buffer and time.monotonic() >= next_flush_deadline)
            )
            if not should_flush:
                continue

            self._flush_scan_batch(self.send_buffer)
            self.send_buffer = []
            next_flush_deadline = time.monotonic() + SCAN_EMIT_INTERVAL_SECONDS

    def _should_process_scan(self, scan):
        bssid = str(scan.get("bssid") or "").strip().upper()
        if not bssid:
            return False

        now = time.time()
        current_signal = scan.get("signal")
        current_classification = scan.get("classification", "UNKNOWN")
        cached = self.last_sent_cache.get(bssid)

        if cached is None:
            return True

        if self._signal_changed(cached.get("signal"), current_signal):
            return True

        if cached.get("classification") != current_classification:
            return True

        return (now - cached.get("last_sent", 0)) > SCAN_DEDUP_MAX_AGE_SECONDS

    def _signal_changed(self, previous_signal, current_signal):
        if previous_signal is None or current_signal is None:
            return previous_signal != current_signal

        try:
            return abs(int(current_signal) - int(previous_signal)) >= SCAN_DEDUP_SIGNAL_DELTA
        except (TypeError, ValueError):
            return previous_signal != current_signal

    def _update_last_sent_cache(self, payload):
        bssid = str(payload.get("bssid") or "").strip().upper()
        if not bssid:
            return

        self.last_sent_cache[bssid] = {
            "signal": payload.get("signal"),
            "classification": payload.get("classification", "UNKNOWN"),
            "last_sent": time.time(),
        }

    def _flush_scan_batch(self, batch):
        if not batch or not self.sio.connected:
            return

        try:
            self.sio.emit("network_scan", self._build_scan_batch_payload(batch))
            self._mark_scan_batch_sent(batch)
        except Exception:
            update_status(backend_status="degraded", message="Network send failed")

    def _build_scan_batch_payload(self, batch):
        return {
            "sensor_id": self.sensor_id,
            "hostname": self.hostname,
            "sent_at": datetime.utcnow().isoformat(),
            "networks": [
                {
                    key: value
                    for key, value in scan.items()
                    if key not in {"sensor_id", "hostname"}
                }
                for scan in batch
            ],
        }

    def _mark_scan_batch_sent(self, batch):
        sample = batch[0]
        mark_sent(
            {
                "ssid": sample.get("ssid"),
                "bssid": sample.get("bssid"),
                "batch_size": len(batch),
            }
        )

    def _build_scan_payload(self, scan):
        uptime = self._format_uptime()
        return {
            "sensor_id": self.sensor_id,
            "hostname": self.hostname,
            "timestamp": scan.get("timestamp") or datetime.utcnow().isoformat(),
            "ssid": scan.get("ssid"),
            "bssid": scan.get("bssid"),
            "channel": scan.get("channel"),
            "signal": scan.get("signal"),
            "encryption": scan.get("encryption"),
            "manufacturer": scan.get("manufacturer", "Unknown"),
            "clients": scan.get("clients", 0),
            "classification": scan.get("classification", "UNKNOWN"),
            "score": scan.get("score", 0),
            "auth": scan.get("auth"),
            "wps": scan.get("wps"),
            "distance": scan.get("distance"),
            "raw_beacon": scan.get("raw_beacon"),
            "uptime": uptime,
            "uptime_seconds": int(time.time() - self.started_at),
        }

    def _format_uptime(self):
        seconds = max(int(time.time() - self.started_at), 0)
        days, seconds = divmod(seconds, 86400)
        hours, seconds = divmod(seconds, 3600)
        minutes, _ = divmod(seconds, 60)

        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes or not parts:
            parts.append(f"{minutes}m")
        return " ".join(parts)