"""
WebSocket Client for ZeinaGuard Sensor
Connects to backend and streams network scan data in real-time

Features:
- Dynamic backend URL resolution (Docker-aware)
- Automatic reconnection with exponential backoff
- Robust error handling and logging
- Local data logging (CSV + JSON) for redundancy
"""

import socketio
import threading
import time
import os
import sys
import json
import csv
from datetime import datetime
from pathlib import Path

# Import event bus for receiving sensor data
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.event_bus import dashboard_queue

# =========================================================
# Configuration
# =========================================================

# Dynamic backend URL resolution
RUN_MODE = os.getenv('RUN_MODE', 'LOCAL')

if RUN_MODE == 'DOCKER':
    # Inside Docker container - use service name
    DEFAULT_BACKEND_URL = 'http://flask-backend:5000'
else:
    # Local development
    DEFAULT_BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:5000')

# Data logging configuration
DATA_LOG_DIR = Path(__file__).parent.parent / 'data-logs'
CSV_ROTATION_INTERVAL = 3600  # Rotate CSV every hour
JSON_ROTATION_INTERVAL = 3600  # Rotate JSON every hour


class WSClient:
    """
    WebSocket client for sensor-to-backend communication.

    Features:
    - Auto-reconnection with exponential backoff
    - Local data logging (CSV + JSON)
    - Graceful shutdown
    - Connection status tracking
    """

    def __init__(self, backend_url=None, token=None, sensor_id='sensor1'):
        """
        Initialize WebSocket client.

        Args:
            backend_url: Backend server URL (auto-detected if None)
            token: Authentication token (required)
            sensor_id: Sensor identifier
        """
        self.backend_url = backend_url or DEFAULT_BACKEND_URL
        self.token = token
        self.sensor_id = sensor_id

        # Initialize Socket.IO client
        self.sio = socketio.Client(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=3,
            reconnection_delay_max=30,
            randomization_factor=0.5,
            logger=True,
            engineio_logger=True
        )

        # State tracking
        self.is_running = False
        self.is_connected = False
        self.thread = None

        # Data logging state
        self._csv_file = None
        self._json_file = None
        self._last_rotation = time.time()
        self._current_session_id = None

        # Connection retry state
        self._retry_count = 0
        self._max_retries = 10

        # Register event handlers
        self._register_handlers()

        # Initialize logging
        self._init_data_logging()

    def _register_handlers(self):
        """Register Socket.IO event handlers."""

        @self.sio.on('connect')
        def _on_connect():
            self.is_connected = True
            self._retry_count = 0
            print(f"[WebSocket] 🟢 Connected to Backend at {self.backend_url}")

            # Register sensor with backend
            self.sio.emit('sensor_register', {
                'sensor_id': self.sensor_id
            })

        @self.sio.on('disconnect')
        def _on_disconnect():
            self.is_connected = False
            print("[WebSocket] 🔴 Disconnected from server")

        @self.sio.on('connect_error')
        def _on_connect_error(data):
            print(f"[WebSocket] ❌ Connection error: {data}")

        @self.sio.on('registration_success')
        def _on_registration_success(data):
            print(f"[WebSocket] ✅ Sensor registered: {data}")

        @self.sio.on('registration_error')
        def _on_registration_error(data):
            print(f"[WebSocket] ❌ Registration failed: {data}")

    def _init_data_logging(self):
        """Initialize local data logging (CSV + JSON)."""
        try:
            # Create data-logs directory if it doesn't exist
            DATA_LOG_DIR.mkdir(parents=True, exist_ok=True)
            print(f"[DataLogger] 📁 Data logs directory: {DATA_LOG_DIR}")

            # Start new session
            self._start_new_session()

        except Exception as e:
            print(f"[DataLogger] ❌ Initialization failed: {e}")

    def _start_new_session(self):
        """Start a new logging session with fresh files."""
        self._current_session_id = datetime.now().strftime('%Y%m%d_%H%M%S')

        # File paths
        self._csv_file = DATA_LOG_DIR / f'network_scan_{self._current_session_id}.csv'
        self._json_file = DATA_LOG_DIR / f'network_scan_{self._current_session_id}.json'

        # Initialize CSV with headers
        headers = [
            'timestamp', 'ssid', 'bssid', 'channel', 'signal_strength',
            'distance', 'auth', 'wps', 'manufacturer', 'uptime',
            'status', 'score', 'elapsed_time'
        ]

        try:
            with open(self._csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            print(f"[DataLogger] 📝 CSV log started: {self._csv_file.name}")
        except Exception as e:
            print(f"[DataLogger] ❌ CSV init failed: {e}")

        # Touch JSON file
        try:
            self._json_file.touch()
            print(f"[DataLogger] 📝 JSON log started: {self._json_file.name}")
        except Exception as e:
            print(f"[DataLogger] ❌ JSON init failed: {e}")

        self._last_rotation = time.time()

    def _rotate_logs_if_needed(self):
        """Rotate log files if they've grown too large or old."""
        now = time.time()

        # Check if rotation is needed (every hour)
        if now - self._last_rotation < CSV_ROTATION_INTERVAL:
            return

        # Check file sizes
        rotate = False

        if self._csv_file and self._csv_file.exists():
            if self._csv_file.stat().st_size > 10 * 1024 * 1024:  # 10MB
                rotate = True

        if self._json_file and self._json_file.exists():
            if self._json_file.stat().st_size > 10 * 1024 * 1024:  # 10MB
                rotate = True

        if rotate:
            print("[DataLogger] 🔄 Rotating log files...")
            self._start_new_session()

    def _log_to_file(self, data):
        """
        Log network scan data to both CSV and JSON files.

        Args:
            data: Dictionary containing scan data
        """
        try:
            # Check for rotation
            self._rotate_logs_if_needed()

            # CSV logging
            if self._csv_file:
                row = [
                    data.get('timestamp', datetime.now().isoformat()),
                    data.get('ssid', ''),
                    data.get('bssid', ''),
                    data.get('channel', ''),
                    data.get('signal', ''),
                    data.get('distance', ''),
                    data.get('auth', ''),
                    data.get('wps', ''),
                    data.get('manufacturer', ''),
                    data.get('uptime', ''),
                    data.get('status', ''),
                    data.get('score', ''),
                    data.get('elapsed_time', '')
                ]

                with open(self._csv_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)

            # JSON logging (append mode, one JSON object per line)
            if self._json_file:
                log_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'session_id': self._current_session_id,
                    'data': data
                }

                with open(self._json_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry) + '\n')

        except Exception as e:
            print(f"[DataLogger] ❌ Write failed: {e}")

    def connect_to_server(self):
        """
        Connect to backend server with automatic reconnection.
        Runs in a loop until stopped.
        """
        if not self.token:
            print("[WebSocket] ❌ Cannot start: No authentication token provided")
            return

        self.is_running = True

        # Start data transmission thread
        self.thread = threading.Thread(
            target=self._data_transmitter,
            daemon=True,
            name='WSDataTransmitter'
        )
        self.thread.start()

        print(f"[WebSocket] 🔄 Connecting to {self.backend_url}...")

        # Main connection loop with reconnection
        while self.is_running:
            try:
                self.sio.connect(
                    self.backend_url,
                    headers={
                        'Authorization': f'Bearer {self.token}'
                    },
                    transports=['websocket'],
                    wait=True
                )
                self.sio.wait()  # Block until disconnected

            except socketio.exceptions.ConnectionError as e:
                self._retry_count += 1
                print(f"[WebSocket] ❌ Connection failed (attempt {self._retry_count}): {e}")

                if self._retry_count >= self._max_retries:
                    print(f"[WebSocket] ❌ Max retries ({self._max_retries}) reached. Stopping.")
                    self.is_running = False
                    break

                # Exponential backoff
                delay = min(30, 5 * (2 ** (self._retry_count - 1)))
                print(f"[WebSocket] ⏳ Retrying in {delay} seconds...")
                time.sleep(delay)

            except Exception as e:
                print(f"[WebSocket] ❌ Unexpected error: {e}")
                time.sleep(5)

        print("[WebSocket] 🛑 Client stopped")

    def stop(self):
        """Gracefully stop the client."""
        print("[WebSocket] 🛑 Stopping WebSocket client...")
        self.is_running = False

        if self.sio.connected:
            self.sio.disconnect()

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)

    def _data_transmitter(self):
        """
        Background thread that transmits data from queue to WebSocket.
        Also logs data locally for redundancy.
        """
        print("[DataTransmitter] 🚀 Started")

        while self.is_running:
            try:
                # Non-blocking queue read with timeout
                try:
                    data = dashboard_queue.get(timeout=1)
                except Exception:
                    # Queue empty or timeout
                    continue

                if not data:
                    continue

                # Check connection status
                if not self.is_connected:
                    print("[DataTransmitter] ⏳ Waiting for connection...")
                    time.sleep(1)
                    continue

                # Handle NETWORK_SCAN data
                if data.get('type') == 'NETWORK_SCAN':
                    event = data.get('event', {})

                    payload = {
                        'sensor_id': self.sensor_id,
                        'ssid': event.get('ssid'),
                        'bssid': event.get('bssid'),
                        'channel': event.get('channel'),
                        'signal': event.get('signal'),
                        'distance': event.get('distance'),
                        'auth': event.get('auth'),
                        'wps': event.get('wps'),
                        'manufacturer': event.get('manufacturer'),
                        'uptime': event.get('uptime'),
                        'raw_beacon': event.get('raw_beacon'),
                        'elapsed_time': event.get('elapsed_time'),
                        'timestamp': event.get('timestamp'),
                        'status': data.get('status'),
                        'score': data.get('score'),
                        'reasons': data.get('reasons')
                    }

                    # Send to backend
                    self.sio.emit('network_scan', payload)
                    print(f"[DataTransmitter] 📡 Sent: {payload['ssid']} ({payload['bssid']})")

                    # Local logging (redundancy)
                    self._log_to_file(payload)

                    continue

                # Handle THREAT data
                event = data.get('event', {})
                payload = {
                    'threat_type': data.get('status'),
                    'ssid': event.get('ssid'),
                    'source_mac': event.get('bssid'),
                    'signal': event.get('signal'),
                    'severity': 'HIGH'
                }

                self.sio.emit('new_threat', payload)
                print(f"[DataTransmitter] 🚨 Threat sent: {payload.get('ssid', 'Unknown')}")

                # Local logging
                self._log_to_file({
                    'type': 'THREAT',
                    **payload
                })

            except Exception as e:
                # Expected during normal operation
                pass

            time.sleep(0.1)

    def get_stats(self):
        """Get client statistics."""
        return {
            'is_running': self.is_running,
            'is_connected': self.is_connected,
            'backend_url': self.backend_url,
            'sensor_id': self.sensor_id,
            'retry_count': self._retry_count,
            'csv_file': str(self._csv_file) if self._csv_file else None,
            'json_file': str(self._json_file) if self._json_file else None
        }
