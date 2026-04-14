"""
Threat Manager for ZeinaGuard Sensor
Analyzes network events, classifies threats, and queues data for transmission

Features:
- Real-time threat classification via RiskEngine
- Local data logging (CSV + JSON) for redundancy
- Dashboard queue integration
- Active containment for confirmed rogues
"""

from core.event_bus import event_queue, containment_queue, dashboard_queue
from detection.risk_engine import RiskEngine
import time
import os
import sys
import csv
import json
from datetime import datetime
from pathlib import Path

# =========================================================
# Configuration
# =========================================================

# Data logging configuration - CRITICAL: Use sensor/data-logs/
DATA_LOG_DIR = Path(__file__).parent.parent / 'data-logs'
CSV_ROTATION_INTERVAL = 3600  # Rotate files every hour
MAX_FILE_SIZE_MB = 50  # Rotate if file exceeds 50MB


class ThreatManager:
    """
    Main threat detection and classification engine.

    Responsibilities:
    - Receive raw network events from sniffer
    - Classify networks (NORMAL, SUSPICIOUS, ROGUE)
    - Log all data locally (CSV + JSON)
    - Queue enriched data for dashboard transmission
    - Queue confirmed rogues for containment
    """

    def __init__(self):
        self.engine = RiskEngine()

        # Deduplication and rate limiting
        self.history = {}  # BSSID -> packet count
        self.last_status = {}  # BSSID -> last classification
        self.confirmed_rogues = set()  # Confirmed rogue BSSIDs

        # Transmission rate limiting
        self.last_sent = {}  # BSSID -> last transmission time
        self.cooldown = 15  # Seconds between transmissions per BSSID

        # UI rate limiting
        self.last_ui_update = {}
        self.ui_interval = 1.0  # Seconds between UI updates per BSSID

        # Data logging
        self._csv_file = None
        self._json_file = None
        self._current_session_id = None
        self._last_rotation = time.time()

        # Initialize logging
        self._init_logs()

    def _init_logs(self):
        """
        Initialize local data logging in sensor/data-logs/ directory.
        Creates CSV and JSON files for redundancy.
        """
        try:
            # Create data-logs directory if it doesn't exist
            DATA_LOG_DIR.mkdir(parents=True, exist_ok=True)
            print(f"[ThreatManager] 📁 Data logs directory: {DATA_LOG_DIR}")

            # Start new session
            self._start_new_session()

        except Exception as e:
            print(f"[ThreatManager] ❌ Log initialization failed: {e}")

    def _start_new_session(self):
        """Start a new logging session with fresh files."""
        self._current_session_id = datetime.now().strftime('%Y%m%d_%H%M%S')

        # File paths
        self._csv_file = DATA_LOG_DIR / f'network_scan_{self._current_session_id}.csv'
        self._json_file = DATA_LOG_DIR / f'network_scan_{self._current_session_id}.json'

        # Initialize CSV with headers
        headers = [
            'timestamp', 'ssid', 'bssid', 'channel', 'signal', 'distance',
            'auth', 'wps', 'manufacturer', 'uptime', 'raw_beacon',
            'elapsed_time', 'encryption', 'clients'
        ]

        try:
            with open(self._csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            print(f"[ThreatManager] 📝 CSV log started: {self._csv_file.name}")
        except Exception as e:
            print(f"[ThreatManager] ❌ CSV init failed: {e}")

        # Touch JSON file
        try:
            self._json_file.touch()
            print(f"[ThreatManager] 📝 JSON log started: {self._json_file.name}")
        except Exception as e:
            print(f"[ThreatManager] ❌ JSON init failed: {e}")

        self._last_rotation = time.time()

    def _rotate_logs_if_needed(self):
        """Rotate log files if they've grown too large or old."""
        now = time.time()
        rotate = False

        # Time-based rotation
        if now - self._last_rotation >= CSV_ROTATION_INTERVAL:
            rotate = True
            print("[ThreatManager] 🔄 Rotating logs (time-based)...")

        # Size-based rotation
        if not rotate and self._csv_file and self._csv_file.exists():
            if self._csv_file.stat().st_size > MAX_FILE_SIZE_MB * 1024 * 1024:
                rotate = True
                print("[ThreatManager] 🔄 Rotating logs (size-based)...")

        if rotate:
            self._start_new_session()

    def log_to_file(self, event):
        """
        Log network event to both CSV and JSON files.

        Args:
            event: Dictionary containing network scan data
        """
        try:
            # Check for rotation
            self._rotate_logs_if_needed()

            # CSV logging
            if self._csv_file:
                row = [
                    event.get('timestamp', datetime.now().isoformat()),
                    event.get('ssid', ''),
                    event.get('bssid', ''),
                    event.get('channel', ''),
                    event.get('signal', ''),
                    event.get('distance', ''),
                    event.get('auth', ''),
                    event.get('wps', ''),
                    event.get('manufacturer', ''),
                    event.get('uptime', ''),
                    event.get('raw_beacon', ''),
                    event.get('elapsed_time', ''),
                    event.get('encryption', ''),
                    event.get('clients', 0)
                ]

                with open(self._csv_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(row)

            # JSON logging (append mode, one JSON object per line - NDJSON format)
            if self._json_file:
                log_entry = {
                    'timestamp': datetime.now().isoformat(),
                    'session_id': self._current_session_id,
                    'event': event
                }

                with open(self._json_file, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

        except Exception as e:
            print(f"[ThreatManager] ❌ Log write failed: {e}")

    def print_event(self, event_summary):
        """
        Update terminal UI with network event (rate-limited).

        Args:
            event_summary: Classified network event dictionary
        """
        bssid = event_summary['bssid']
        now = time.time()

        # Rate limit UI updates
        if bssid not in self.last_ui_update or \
           now - self.last_ui_update[bssid] > self.ui_interval:

            try:
                from ui.terminal_ui import update_ap
                update_ap(event_summary)
            except ImportError:
                pass  # UI not available (e.g., in Docker)
            except Exception as e:
                print(f"[ThreatManager] ⚠️ UI update failed: {e}")

            self.last_ui_update[bssid] = now

    def handle_removal(self, bssid):
        """
        Handle AP removal from sniffer (when beacon timeout expires).

        Args:
            bssid: BSSID of removed access point
        """
        try:
            from ui.terminal_ui import remove_ap
            remove_ap(bssid)
        except (ImportError, Exception):
            pass  # UI not available or failed

        print(f"❌ AP REMOVED: {bssid}")

        # Clean up internal state
        self.history.pop(bssid, None)
        self.last_status.pop(bssid, None)
        self.last_sent.pop(bssid, None)
        self.last_ui_update.pop(bssid, None)

        # Notify dashboard
        dashboard_queue.put({
            'type': 'REMOVED',
            'bssid': bssid
        })

    def start(self):
        """
        Main processing loop.

        Processes events from event_queue:
        1. Log to file (CSV + JSON)
        2. Classify threat level
        3. Update UI
        4. Queue for dashboard transmission
        5. Queue for containment (if confirmed rogue)
        """
        print("[ThreatManager] 🚀 Starting threat detection loop...")

        while True:
            try:
                # Blocking get from event queue
                event = event_queue.get()

                # Handle AP removal events
                if isinstance(event, dict) and event.get('type') == 'AP_REMOVED':
                    self.handle_removal(event['bssid'])
                    continue

                # Skip invalid events
                if not event or not isinstance(event, dict):
                    continue

                # ----- Step 1: Log to file (redundancy) -----
                self.log_to_file(event)

                # ----- Step 2: Analyze and classify -----
                event_summary = self.engine.analyze(event)

                bssid = event_summary['bssid']
                status = event_summary['classification']
                score = event_summary['score']
                reasons = event_summary['reasons']

                # ----- Step 3: Update history -----
                self.history[bssid] = self.history.get(bssid, 0) + 1

                # ----- Step 4: Update UI (rate-limited) -----
                self.print_event(event_summary)

                # ----- Step 5: Save last status -----
                self.last_status[bssid] = status

                # ----- Step 6: Queue for dashboard transmission -----
                # Send ALL detected APs (not just threats) for complete visibility
                now = time.time()
                if bssid not in self.last_sent or now - self.last_sent[bssid] > self.cooldown:

                    # Enriched network scan payload
                    network_data = {
                        'type': 'NETWORK_SCAN',
                        'status': status,
                        'score': score,
                        'reasons': reasons,
                        'event': event  # Full event data
                    }

                    dashboard_queue.put(network_data)
                    self.last_sent[bssid] = now

                # ----- Step 7: Rogue confirmation and containment -----
                # Require 3 consecutive detections before confirming rogue
                if status == 'ROGUE' and \
                   self.history[bssid] >= 3 and \
                   bssid not in self.confirmed_rogues:

                    self.confirmed_rogues.add(bssid)

                    print("\n" + "=" * 50)
                    print("🚨 ROGUE ACCESS POINT CONFIRMED 🚨")
                    print(f"SSID  : {event_summary['ssid']}")
                    print(f"BSSID : {event_summary['bssid']}")
                    print(f"Score : {score}")
                    print(f"Reasons: {reasons}")
                    print("=" * 50)

                    # Queue for active containment (deauth attack)
                    threat = {
                        'status': status,
                        'score': score,
                        'reasons': reasons,
                        'event': event_summary
                    }

                    containment_queue.put(threat)

            except KeyboardInterrupt:
                print("\n[ThreatManager] 🛑 Stopping...")
                break
            except Exception as e:
                print(f"[ThreatManager] ❌ Error in processing loop: {e}", exc_info=True)
                time.sleep(1)
