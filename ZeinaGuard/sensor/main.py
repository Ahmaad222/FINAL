import os
import sys
import subprocess
import importlib.util
import shutil

# --------------------------------
# 📦 Auto Dependency Handler
# --------------------------------
DEPENDENCIES = {
    "scapy": "scapy",
    "python-socketio": "socketio",
    "websocket-client": "websocket",
    "requests": "requests",
    "rich": "rich",
    "readchar": "readchar",
    "mac-vendor-lookup": "mac_vendor_lookup"
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
import time
from monitoring.sniffer import start_monitoring
from detection.threat_manager import ThreatManager
from prevention.response_engine import ResponseEngine
from communication.ws_client import WSClient
from communication.api_client import APIClient
from ui.terminal_ui import run_terminal_ui
import config

def main():
    # --------------------------------
    # 🛠️ DEBUG_RESET Check (Part 3)
    # --------------------------------
    if os.getenv("DEBUG_RESET", "false").lower() == "true":
        print("[DEBUG] 🧹 DEBUG_RESET is true. Clearing old logs...")
        log_dir = "/app/data_logs" if os.path.exists("/app") else "data_logs"
        if os.path.exists(log_dir):
            try:
                for filename in os.listdir(log_dir):
                    file_path = os.path.join(log_dir, filename)
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                print("[DEBUG] ✅ Logs cleared.")
            except Exception as e:
                print(f"[DEBUG] ❌ Error clearing logs: {e}")

    # --------------------------------
    # 🛠️ Command Line Arguments
    # --------------------------------
    if len(sys.argv) > 1:
        provided_iface = sys.argv[1]
        print(f"🔧 Using CLI provided interface: {provided_iface}")
        config.INTERFACE = provided_iface

    # Validate interface
    if os.name != 'nt' and not os.path.exists(f"/sys/class/net/{config.INTERFACE}"):
        print(f"❌ Error: Interface '{config.INTERFACE}' not found!")
        sys.exit(1)

    print("🚀 Starting ZeinaGuard Sensor...")

    # --------------------------------
    # 🌐 Dynamic Backend Resolution
    # --------------------------------
    backend_url = config.BACKEND_URL
    sensor_name = os.getenv("SENSOR_USERNAME", "sensor1") # Use as name
    print(f"🔗 Target Backend: {backend_url} | Sensor Name: {sensor_name}")

    # --------------------------------
    # Try Backend Authentication
    # --------------------------------
    token = None
    ws = None
    
    max_auth_retries = int(os.getenv("MAX_AUTH_RETRIES", "10"))
    retry_delay = int(os.getenv("AUTH_RETRY_DELAY", "5"))

    for attempt in range(1, max_auth_retries + 1):
        try:
            api = APIClient(backend_url=backend_url)
            token = api.authenticate_sensor()

            if token:
                print(f"✅ Sensor authenticated with backend.")
                ws = WSClient(backend_url=backend_url, token=token, sensor_name=sensor_name)

                ws_thread = threading.Thread(
                    target=ws.connect_to_server,
                    daemon=True
                )
                ws_thread.start()
                break 
            
            print(f"⚠️ Auth attempt {attempt}/{max_auth_retries} failed. Retrying in {retry_delay}s...")
            time.sleep(retry_delay)

        except Exception as e:
            print(f"⚠️ Connection failed on attempt {attempt}: {e}")
            time.sleep(retry_delay)
    
    if not token:
        print("❌ Failed to authenticate. Running in OFFLINE MODE.")

    # --------------------------------
    # 🔥 Terminal UI Thread
    # --------------------------------
    if config.ENABLE_TUI:
        print("🖥️ Starting Terminal UI...")
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
