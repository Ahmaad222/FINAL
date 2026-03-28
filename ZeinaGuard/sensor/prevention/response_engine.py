import threading
from core.event_bus import containment_queue
from config import ENABLE_ACTIVE_CONTAINMENT, INTERFACE
from prevention.containment_engine import ContainmentEngine
from monitoring.sniffer import clients_map

class ResponseEngine:
    def start(self):
        containment = ContainmentEngine(INTERFACE)

        while True:
            # 🚀 بيسحب من طابور الأكشن بس
            threat = containment_queue.get()

            print("\n🛡️ [Response Engine] Preparing counter-measures...")

            if ENABLE_ACTIVE_CONTAINMENT:
                clients = clients_map.get(threat['event']['bssid'], set())
                
                # 🚀 نشغل الهجوم المضاد في Thread منفصل عشان الـ ResponseEngine مايعطلش
                attack_thread = threading.Thread(
                    target=containment.contain,
                    args=(threat['event']['bssid'], clients, threat['event']['channel']),
                    daemon=True
                )
                attack_thread.start()
            else:
                print("[Response Engine] Active containment is DISABLED in config.")
