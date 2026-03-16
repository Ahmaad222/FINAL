from core.event_bus import event_queue, containment_queue, dashboard_queue
from detection.risk_engine import RiskEngine
import time
from ui.terminal_ui import update_ap, remove_ap


class ThreatManager:

    def __init__(self):

        self.engine = RiskEngine()

        self.history = {}
        self.last_status = {}
        self.confirmed_rogues = set()

        self.last_sent = {}
        self.cooldown = 15

    # 🔥 بدل print -> update UI
    def print_event(self, event_summary):
        update_ap(event_summary)

    def handle_removal(self, bssid):

        # ❌ إزالة من UI
        remove_ap(bssid)

        print(f"❌ AP REMOVED: {bssid}")

        # تنظيف
        self.history.pop(bssid, None)
        self.last_status.pop(bssid, None)
        self.last_sent.pop(bssid, None)

        # notify dashboard (بتاع زميلك)
        dashboard_queue.put({
            "type": "REMOVED",
            "bssid": bssid
        })

    def start(self):

        while True:

            event = event_queue.get()

            # 🔥 AP removed
            if isinstance(event, dict) and event.get("type") == "AP_REMOVED":
                self.handle_removal(event["bssid"])
                continue

            # 🔥 تحليل
            event_summary = self.engine.analyze(event)

            bssid = event_summary["bssid"]
            status = event_summary["classification"]
            score = event_summary["score"]
            reasons = event_summary["reasons"]

            # history
            self.history[bssid] = self.history.get(bssid, 0) + 1

            # update UI عند التغيير بس
            if bssid not in self.last_status or self.last_status[bssid] != status:
                self.print_event(event_summary)
                self.last_status[bssid] = status

            # --------------------------
            # Dashboard (زميلك)
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

                print("\n🚨 ROGUE ACCESS POINT CONFIRMED 🚨")
                print(f"SSID  : {event_summary['ssid']}")
                print(f"BSSID : {event_summary['bssid']}")
                print("=" * 50)

                containment_queue.put(threat)