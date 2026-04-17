import os
import subprocess
import sys
import threading


REQUIRED_PACKAGES = {
    "flask": "flask",
    "flask-socketio": "flask_socketio",
    "python-socketio": "socketio",
    "redis": "redis",
    "requests": "requests",
    "scapy": "scapy",
    "rich": "rich",
    "readchar": "readchar",
    "flask-sqlalchemy": "flask_sqlalchemy",
}


def install_missing_packages():
    missing = []

    for package, module in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if not missing:
        return

    for pkg in missing:
        print(f"Missing package: {pkg}")

    choice = input("Install missing packages now? (y/n): ").lower()
    if choice != "y":
        sys.exit(1)

    subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


def main():
    install_missing_packages()

    from communication.api_client import APIClient
    from communication.ws_client import WSClient
    from detection.threat_manager import ThreatManager
    from monitoring.sniffer import start_monitoring
    from prevention.response_engine import ResponseEngine
    from ui.terminal_ui import run_terminal_ui, update_status

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print("Warning: not running as root. Packet capture may fail.")

    ui_thread = threading.Thread(target=run_terminal_ui, daemon=True, name="TerminalUI")
    ui_thread.start()
    update_status(sensor_status="starting", backend_status="connecting", message="Booting sensor")

    token = None
    try:
        api = APIClient()
        token = api.authenticate_sensor()
        update_status(
            backend_status="authenticated" if token else "offline",
            message="Backend authenticated" if token else "Offline mode: local logging only",
        )
    except Exception:
        update_status(backend_status="offline", message="Backend unavailable: local logging only")

    ws_client = WSClient(token=token)
    threading.Thread(target=ws_client.start, daemon=True, name="WSClient").start()

    threat_manager = ThreatManager()
    threading.Thread(target=threat_manager.start, daemon=True, name="ThreatManager").start()

    response_engine = ResponseEngine()
    threading.Thread(target=response_engine.start, daemon=True, name="ResponseEngine").start()

    update_status(sensor_status="monitoring", message="Wireless monitoring active")
    start_monitoring()


if __name__ == "__main__":
    main()
