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


import config # Import config first to allow runtime modification

def main():
    # --------------------------------
    # 🛠️ Command Line Arguments (Interface)
    # --------------------------------
    if len(sys.argv) > 1:
        provided_iface = sys.argv[1]
        print(f"🔧 Using CLI provided interface: {provided_iface}")
        config.INTERFACE = provided_iface
    else:
        print(f"ℹ️ No interface provided via CLI, using config default: {config.INTERFACE}")

    # Validate interface
    if os.name != 'nt' and not os.path.exists(f"/sys/class/net/{config.INTERFACE}"):
        print(f"❌ Error: Interface '{config.INTERFACE}' not found on this system!")
        sys.exit(1)

    print("🚀 Starting ZeinaGuard Sensor...")

    # --------------------------------
    # 🌐 Dynamic Backend Resolution
    # --------------------------------
    backend_host = os.getenv("ZEINAGUARD_BACKEND", config.BACKEND_HOST)
    backend_port = config.BACKEND_PORT
    backend_url = f"http://{backend_host}:{backend_port}"

    # --------------------------------
    # Try Backend Authentication
    # --------------------------------

    token = None
    ws = None
    
    max_auth_retries = 2
    for attempt in range(max_auth_retries + 1):
        try:
            api = APIClient(backend_url=backend_url)
            token = api.authenticate_sensor()

            if token:
                print(f"✅ Sensor authenticated with backend at {backend_url}")
                ws = WSClient(backend_url=backend_url, token=token)

                ws_thread = threading.Thread(
                    target=ws.connect_to_server,
                    daemon=True
                )
                ws_thread.start()
                break # Success!

            else:
                if attempt < max_auth_retries:
                    print(f"⚠️ Connection to {backend_url} failed.")
                    new_ip = input("👉 Enter Backend Server IP (or press Enter to retry): ").strip()
                    if new_ip:
                        backend_url = f"http://{new_ip}:{backend_port}"
                else:
                    print("⚠️ Running in OFFLINE MODE after multiple failed attempts.")

        except Exception as e:
            print(f"⚠️ Connection failed: {e}")
            if attempt < max_auth_retries:
                new_ip = input("👉 Enter Backend Server IP: ").strip()
                if new_ip:
                    backend_url = f"http://{new_ip}:{backend_port}"
            else:
                print("⚠️ Running in OFFLINE MODE")

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
