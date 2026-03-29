import os
import sys
import subprocess
import importlib.util

# --------------------------------
# 📦 Auto Dependency Handler
# --------------------------------
DEPENDENCIES = {
    "scapy": "scapy",
    "python-socketio": "socketio",
    "websocket-client": "websocket",
    "requests": "requests",
    "rich": "rich",
    "readchar": "readchar"
}

def ensure_dependencies():
    """Checks and installs missing dependencies at runtime."""
    for package, module in DEPENDENCIES.items():
        if importlib.util.find_spec(module) is None:
            print(f"Missing dependency: {package} → installing...")
            try:
                # Use sys.executable to ensure we install to the current environment (venv or system)
                subprocess.check_call([sys.executable, "-m", "pip", "install", package], 
                                      stdout=subprocess.DEVNULL, 
                                      stderr=subprocess.STDOUT)
            except Exception as e:
                print(f"❌ Failed to install {package}: {e}")
                sys.exit(1)

ensure_dependencies()

# --------------------------------
# ⚠️ Root Check (for scapy)
# --------------------------------
if os.name != 'nt' and os.geteuid() != 0:
    print("⚠️ Warning: You are not running as root.")
    print("👉 Scapy requires root privileges for raw packet operations.")
    print("👉 Run with: sudo python3 main.py\n")

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
