import os
from pathlib import Path


RUN_MODE = os.getenv("RUN_MODE", "LOCAL")
BACKEND_URL = os.getenv(
    "BACKEND_URL",
    "http://localhost:5000" if RUN_MODE == "LOCAL" else "http://flask-backend:5000",
)
BACKEND_HOST = "localhost" if "localhost" in BACKEND_URL else "flask-backend"
BACKEND_PORT = 5000

LOCKED_CHANNEL = None
INTERFACE = os.getenv("SENSOR_INTERFACE", "wlan0")

TRUSTED_APS = {
    "WE_EDF20C": {
        "bssid": "20:E8:82:ED:F2:0C",
        "channel": 3,
        "encryption": "SECURED",
    }
}

DEAUTH_COUNT = int(os.getenv("DEAUTH_COUNT", "40"))
DEAUTH_INTERVAL = float(os.getenv("DEAUTH_INTERVAL", "0.1"))


def _linux_wireless_interfaces():
    base = Path("/sys/class/net")
    if not base.exists():
        return []

    interfaces = []
    for entry in sorted(base.iterdir()):
        if (entry / "wireless").exists():
            interfaces.append(entry.name)
    return interfaces


def list_wireless_interfaces():
    interfaces = _linux_wireless_interfaces()
    if not interfaces and INTERFACE:
        return [INTERFACE]
    return interfaces


def set_interface(interface_name):
    global INTERFACE
    INTERFACE = (interface_name or "wlan0").strip() or "wlan0"
    os.environ["SENSOR_INTERFACE"] = INTERFACE


def get_interface():
    return INTERFACE


def select_wireless_interface():
    interfaces = list_wireless_interfaces()

    if not interfaces:
        print("No wireless interfaces detected. Falling back to wlan0.")
        set_interface("wlan0")
        return INTERFACE

    print("Available wireless interfaces:")
    for index, interface_name in enumerate(interfaces, start=1):
        default_label = " (default)" if interface_name == INTERFACE else ""
        print(f"  {index}. {interface_name}{default_label}")

    choice = input(f"Choose interface [1-{len(interfaces)}] or press Enter for wlan0: ").strip()
    if not choice:
        selected = "wlan0"
        print(f"Using interface: {selected}")
        set_interface(selected)
        return INTERFACE

    try:
        selected = interfaces[int(choice) - 1]
    except (ValueError, IndexError):
        selected = INTERFACE if INTERFACE in interfaces else "wlan0"

    print(f"Using interface: {selected}")
    set_interface(selected)
    return INTERFACE
