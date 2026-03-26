import subprocess
import sys
import os

# --------------------------------
# 🔍 Check & Install Dependencies
# --------------------------------

REQUIRED_PACKAGES = {
    "flask": "flask",
    "flask-socketio": "flask_socketio",
    "python-socketio": "socketio",
    "redis": "redis",
    "requests": "requests",
    "scapy": "scapy",
    "rich": "rich",
    "readchar": "readchar",
    "flask-sqlalchemy": "flask_sqlalchemy"
}


def install_missing_packages():
    missing = []

    for package, module in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)

    if missing:
        print("⚠️ Missing packages detected:")
        for pkg in missing:
            print(f" - {pkg}")

        choice = input("❓ Install missing packages now? (y/n): ").lower()

        if choice == "y":
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
                print("✅ Packages installed successfully\n")
            except Exception as e:
                print("❌ Failed to install packages:", e)
                sys.exit(1)
        else:
            print("❌ Cannot continue without required packages.")
            sys.exit(1)


install_missing_packages()

# --------------------------------
# ⚠️ Root Check (for scapy)
# --------------------------------
if os.geteuid() != 0:
    print("⚠️ Warning: You are not running as root.")
    print("👉 Scapy may not work correctly.")
    print("👉 Run with: sudo python3 main.py\n")

# --------------------------------
# باقي imports
# --------------------------------

import threading

from monitoring.sniffer import start_monitoring
from detection.threat_manager import ThreatManager
from prevention.response_engine import ResponseEngine
from communication.ws_client import WSClient
from communication.api_client import APIClient

# 🔥 Terminal UI
from ui.terminal_ui import run_terminal_ui


def main():

    print("🚀 Starting ZeinaGuard Sensor...")

    # --------------------------------
    # Try Backend Authentication
    # --------------------------------

    token = None
    ws = None

    try:
        api = APIClient()
        token = api.authenticate_sensor()

        if token:
            print("✅ Sensor authenticated with backend")

            ws = WSClient(token=token)

            ws_thread = threading.Thread(
                target=ws.connect_to_server,
                daemon=True
            )
            ws_thread.start()

        else:
            print("⚠️ Backend not available — running in OFFLINE MODE")

    except Exception as e:
        print("⚠️ Backend connection failed — running OFFLINE")
        print(e)

    # --------------------------------
    # 🔥 Terminal UI Thread
    # --------------------------------

    ui_thread = threading.Thread(
        target=run_terminal_ui,
        daemon=True
    )
    ui_thread.start()

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
    # Monitoring (Sniffer)
    # --------------------------------

    print("📡 Starting wireless monitoring...")

    start_monitoring()


if __name__ == "__main__":
    main()
