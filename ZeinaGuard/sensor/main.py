import threading

from monitoring.sniffer import start_monitoring
from detection.threat_manager import ThreatManager
from prevention.response_engine import ResponseEngine
from communication.ws_client import WSClient
from communication.api_client import APIClient


def main():

    print("🚀 Starting ZeinaGuard Sensor...")

    # --------------------------------
    # Authenticate
    # --------------------------------

    api = APIClient()

    token = api.authenticate_sensor()

    if not token:
        print("❌ Sensor authentication failed")
        return

    # --------------------------------
    # WebSocket
    # --------------------------------

    ws = WSClient(token=token)

    ws_thread = threading.Thread(
        target=ws.connect_to_server,
        daemon=True
    )

    ws_thread.start()

    # --------------------------------
    # Threat Manager
    # --------------------------------

    threat_manager = ThreatManager()

    t1 = threading.Thread(
        target=threat_manager.start,
        daemon=True
    )

    t1.start()

    # --------------------------------
    # Response Engine
    # --------------------------------

    response_engine = ResponseEngine()

    t2 = threading.Thread(
        target=response_engine.start,
        daemon=True
    )

    t2.start()

    # --------------------------------
    # Monitoring
    # --------------------------------

    start_monitoring()


if __name__ == "__main__":
    main()