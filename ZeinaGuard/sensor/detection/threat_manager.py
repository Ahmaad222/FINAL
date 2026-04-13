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
        
        # 🚀 Logging Setup (Part 1 & 4)
        # In Docker, we use /app/data_logs. Locally, we might use data_logs.
        base_log_dir = "/app/data_logs" if os.path.exists("/app") else "data_logs"
        self.session_id = datetime.now().strftime("session_%Y%m%d_%H%M%S")
        self.session_dir = os.path.join(base_log_dir, self.session_id)
        
        self.networks_csv = os.path.join(self.session_dir, "networks.csv")
        self.networks_json = os.path.join(self.session_dir, "networks.json")
        self.clients_csv = os.path.join(self.session_dir, "clients.csv")
        
        self._init_logs()

    def _init_logs(self):
        """Initializes the session folder and CSV files with headers."""
        if not os.path.exists(self.session_dir):
            try:
                os.makedirs(self.session_dir, exist_ok=True)
                print(f"[LOG] 📂 Created session folder: {self.session_dir}")
            except Exception as e:
                print(f"[LOG] ❌ Failed to create log directory: {e}")
            
        # Networks CSV Headers
        headers = [
            "Timestamp", "SSID", "BSSID", "Channel", "Signal", "Distance", 
            "Auth", "WPS", "Manufacturer", "Uptime", "Fingerprint", "ClientsCount", "Elapsed"
        ]
        try:
            with open(self.networks_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                
            # Clients CSV Headers
            with open(self.clients_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "ClientMAC", "AP_BSSID", "Vendor"])
        except Exception as e:
            print(f"[LOG] ❌ Failed to initialize CSV files: {e}")

    def log_to_file(self, event):
        """Logs the network event to CSV and JSON (Part 4)."""
        if not os.path.exists(self.session_dir): return

        try:
            # 1. Networks CSV
            row = [
                event.get("timestamp"),
                event.get("ssid"),
                event.get("bssid"),
                event.get("channel"),
                event.get("signal"),
                event.get("distance"),
                event.get("auth"),
                event.get("wps"),
                event.get("manufacturer"),
                event.get("uptime"),
                event.get("fingerprint"),
                event.get("clients_count"),
                event.get("elapsed_time")
            ]
            with open(self.networks_csv, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(row)
                
            # 2. Networks JSON (one object per line for easy streaming/reading)
            with open(self.networks_json, 'a', encoding='utf-8') as f:
                f.write(json.dumps(event) + "\n")
                
            # 3. Clients CSV (if any clients found)
            clients = event.get("clients", [])
            if clients:
                with open(self.clients_csv, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    for client in clients:
                        writer.writerow([
                            event.get("timestamp"),
                            client.get("mac"),
                            event.get("bssid"),
                            client.get("vendor")
                        ])
        except Exception as e:
            # print(f"[LOG] ❌ Error writing to log files: {e}")
            pass

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

            # 🚀 Log Advanced Data (Part 4)
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
