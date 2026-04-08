import os
import sys
import subprocess
import importlib.util
import time

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
# from ui.terminal_ui import run_terminal_ui # Disable UI in Docker to avoid TTY issues

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
        print(f"ℹ️ Using interface: {config.INTERFACE}")

    # Validate interface (only if not in a container or if requested)
    if os.name != 'nt' and not os.path.exists(f"/sys/class/net/{config.INTERFACE}"):
        print(f"⚠️ Warning: Interface '{config.INTERFACE}' not found. Sniffing may fail.")

    print("🚀 Starting ZeinaGuard Sensor...")

    # --------------------------------
    # 🌐 Dynamic Backend Resolution
    # --------------------------------
    backend_host = config.BACKEND_HOST
    backend_port = config.BACKEND_PORT
    backend_url = f"http://{backend_host}:{backend_port}"

    print(f"📡 Backend Target: {backend_url}")

    # --------------------------------
    # Try Backend Authentication (with infinite retry for Docker)
    # --------------------------------

    token = None
    ws = None
    
    while token is None:
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
                print(f"⚠️ Authentication failed. Retrying in 10 seconds...")
                time.sleep(10)

        except Exception as e:
            print(f"⚠️ Connection failed: {e}. Retrying in 10 seconds...")
            time.sleep(10)

    # --------------------------------
    # 🔥 Terminal UI Thread (Disabled in Docker)
    # --------------------------------
    # ui_thread = threading.Thread(
    #     target=run_terminal_ui,
    #     daemon=True
    # )
    # ui_thread.start()

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

    # We use a try-except here because scapy might crash if interface is invalid
    try:
        start_monitoring()
    except KeyboardInterrupt:
        print("Stopping sensor...")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal Sniffer Error: {e}")
        # Keep alive for other threads if needed, or exit
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
