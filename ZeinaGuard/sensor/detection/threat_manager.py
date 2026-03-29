from core.event_bus import event_queue, containment_queue, dashboard_queue
from detection.risk_engine import RiskEngine
import time
import os
import csv
import json
from datetime import datetime
from ui.terminal_ui import update_ap, remove_ap


class ThreatManager:

    def __init__(self):

        self.engine = RiskEngine()

        self.history = {}
        self.last_status = {}
        self.confirmed_rogues = set()

        self.last_sent = {}
        self.cooldown = 15

        # 🔥 UI rate limit
        self.last_ui_update = {}
        self.ui_interval = 1.0   # ثانية
        
        # 🚀 Logging Setup
        self.log_dir = "data_logs"
        self.session_id = datetime.now().strftime("%Y%m%d_%HH%MM%SS")
        self.csv_file = os.path.join(self.log_dir, f"scan_{self.session_id}.csv")
        self.json_file = os.path.join(self.log_dir, f"scan_{self.session_id}.json")
        self._init_logs()

    def _init_logs(self):
        """Initializes the CSV file with headers."""
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)
            
        headers = [
            "SSID", "BSSID", "Channel", "PWR", "Distance", 
            "Auth", "WPS", "Manufacturer", "Uptime", "Beacons", "Timestamp"
        ]
        with open(self.csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(headers)

    def log_to_file(self, event):
        """Logs the network event to CSV and JSON."""
        # CSV Logging
        row = [
            event.get("ssid"),
            event.get("bssid"),
            event.get("channel"),
            event.get("signal"),
            event.get("distance"),
            event.get("auth"),
            event.get("wps"),
            event.get("manufacturer"),
            event.get("uptime"),
            event.get("raw_beacon"),
            event.get("timestamp")
        ]
        with open(self.csv_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(row)
            
        # JSON Logging (Append style)
        with open(self.json_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(event) + "\n")

    # ---------------------------
    # Update UI
    # ---------------------------

    def print_event(self, event_summary):

        bssid = event_summary["bssid"]
        now = time.time()

        # لو أول مرة أو مر وقت كفاية
        if bssid not in self.last_ui_update or \
           now - self.last_ui_update[bssid] > self.ui_interval:

            update_ap(event_summary)

            self.last_ui_update[bssid] = now

    # ---------------------------
    # AP removal
    # ---------------------------

    def handle_removal(self, bssid):

        remove_ap(bssid)

        print(f"❌ AP REMOVED: {bssid}")

        self.history.pop(bssid, None)
        self.last_status.pop(bssid, None)
        self.last_sent.pop(bssid, None)
        self.last_ui_update.pop(bssid, None)

        dashboard_queue.put({
            "type": "REMOVED",
            "bssid": bssid
        })

    # ---------------------------
    # Main loop
    # ---------------------------

    def start(self):

        while True:

            event = event_queue.get()

            # -----------------------
            # AP removed
            # -----------------------

            if isinstance(event, dict) and event.get("type") == "AP_REMOVED":
                self.handle_removal(event["bssid"])
                continue

            # 🚀 Log Advanced Data
            self.log_to_file(event)

            # -----------------------
            # Analysis
            # -----------------------

            event_summary = self.engine.analyze(event)

            bssid = event_summary["bssid"]
            status = event_summary["classification"]
            score = event_summary["score"]
            reasons = event_summary["reasons"]

            # -----------------------
            # History
            # -----------------------

            self.history[bssid] = self.history.get(bssid, 0) + 1

            # -----------------------
            # UI update (rate limited)
            # -----------------------

            self.print_event(event_summary)

            # حفظ آخر حالة
            self.last_status[bssid] = status

            # -----------------------
            # Dashboard / Enriched Data Feed
            # -----------------------

            # We send ALL detected APs to the enriched feed, not just SUSPICIOUS/ROGUE
            # but we use a cooldown to avoid flooding.
            
            now = time.time()
            if bssid not in self.last_sent or now - self.last_sent[bssid] > self.cooldown:
                
                # Payload for enriched network data
                network_data = {
                    "type": "NETWORK_SCAN",
                    "status": status,
                    "score": score,
                    "reasons": reasons,
                    "event": event # Contains all enriched fields
                }

                dashboard_queue.put(network_data)
                self.last_sent[bssid] = now

            # -----------------------
            # Rogue confirmation (Counter-measures)
            # -----------------------

            if status == "ROGUE" and \
               self.history[bssid] >= 3 and \
               bssid not in self.confirmed_rogues:

                self.confirmed_rogues.add(bssid)

                print("\n🚨 ROGUE ACCESS POINT CONFIRMED 🚨")
                print(f"SSID  : {event_summary['ssid']}")
                print(f"BSSID : {event_summary['bssid']}")
                print("=" * 50)
                
                threat = {
                    "status": status,
                    "score": score,
                    "reasons": reasons,
                    "event": event_summary
                }

                containment_queue.put(threat)
