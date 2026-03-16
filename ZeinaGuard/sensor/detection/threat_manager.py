from core.event_bus import event_queue, containment_queue, dashboard_queue
from detection.risk_engine import RiskEngine
import datetime
import time


class ThreatManager:

    def __init__(self):

        self.engine = RiskEngine()

        self.history = {}
        self.last_status = {}
        self.confirmed_rogues = set()

        self.last_sent = {}
        self.cooldown = 15

    def print_event(self, event_summary):

        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        print("-" * 60)
        print(f"[{timestamp}] NEW ACCESS POINT DETECTED")
        print(f"SSID      : {event_summary['ssid']}")
        print(f"BSSID     : {event_summary['bssid']}")
        print(f"Channel   : {event_summary['channel']}")
        print(f"Status    : {event_summary['classification']}")
        print(f"Score     : {event_summary['score']}")
        print("-" * 60)

    def handle_removal(self, bssid):

        print(f"\n❌ AP REMOVED: {bssid}\n")

        # تنظيف
        self.history.pop(bssid, None)
        self.last_status.pop(bssid, None)
        self.last_sent.pop(bssid, None)

        # notify dashboard
        dashboard_queue.put({
            "type": "REMOVED",
            "bssid": bssid
        })

    def start(self):

        while True:

            event = event_queue.get()

            # 🔥 لو AP اتشال
            if isinstance(event, dict) and event.get("type") == "AP_REMOVED":
                self.handle_removal(event["bssid"])
                continue

            # 🔥 تحليل طبيعي
            event_summary = self.engine.analyze(event)

            bssid = event_summary["bssid"]
            status = event_summary["classification"]
            score = event_summary["score"]
            reasons = event_summary["reasons"]

            # history
            self.history[bssid] = self.history.get(bssid, 0) + 1

            # print عند التغيير بس
            if bssid not in self.last_status or self.last_status[bssid] != status:
                self.print_event(event_summary)
                self.last_status[bssid] = status

            # --------------------------
            # Dashboard
            # --------------------------
            if status in ["SUSPICIOUS", "ROGUE"]:

                threat = {
                    "status": status,
                    "score": score,
                    "reasons": reasons,
                    "event": event_summary
                }

                now = time.time()

                if bssid not in self.last_sent or now - self.last_sent[bssid] > self.cooldown:
                    dashboard_queue.put(threat)
                    self.last_sent[bssid] = now

            # --------------------------
            # Rogue confirmation
            # --------------------------
            if status == "ROGUE" and self.history[bssid] >= 3 and bssid not in self.confirmed_rogues:

                self.confirmed_rogues.add(bssid)

                print("\n🚨🚨🚨 ROGUE ACCESS POINT CONFIRMED 🚨🚨🚨")
                print(f"SSID      : {event_summary['ssid']}")
                print(f"BSSID     : {event_summary['bssid']}")
                print("=" * 60)

                containment_queue.put(threat)