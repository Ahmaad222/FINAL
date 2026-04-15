import threading

from config import ENABLE_ACTIVE_CONTAINMENT, INTERFACE
from core.event_bus import containment_queue
from monitoring.sniffer import clients_map
from prevention.containment_engine import ContainmentEngine
from ui.terminal_ui import update_status


class ResponseEngine:
    def start(self):
        containment = ContainmentEngine(INTERFACE)

        while True:
            threat = containment_queue.get()
            update_status(message="Preparing containment response")

            if ENABLE_ACTIVE_CONTAINMENT:
                clients = clients_map.get(threat["event"]["bssid"], set())
                attack_thread = threading.Thread(
                    target=containment.contain,
                    args=(threat["event"]["bssid"], clients, threat["event"]["channel"]),
                    daemon=True,
                )
                attack_thread.start()
            else:
                update_status(message="Active containment disabled")
