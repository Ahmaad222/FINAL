import os
import sys
from pathlib import Path
from urllib.parse import urlparse


BACKEND_URL = os.getenv("BACKEND_URL", os.getenv("ZEINAGUARD_BACKEND_URL", "http://localhost:5000"))
_parsed_backend_url = urlparse(BACKEND_URL)
BACKEND_HOST = _parsed_backend_url.hostname or "localhost"
BACKEND_PORT = _parsed_backend_url.port or 5000

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


def _default_interface(interfaces):
    configured = (INTERFACE or "").strip()
    if configured and configured in interfaces:
        return configured
    if "wlan0" in interfaces:
        return "wlan0"
    return interfaces[0] if interfaces else "wlan0"


def _can_prompt_for_interface():
    if os.getenv("ZEINAGUARD_NONINTERACTIVE", "").strip() == "1":
        return False
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


def select_wireless_interface():
    interfaces = list_wireless_interfaces()

    if not interfaces:
        print("No wireless interfaces detected. Falling back to wlan0.")
        set_interface("wlan0")
        return INTERFACE

    selected = _default_interface(interfaces)

    if not _can_prompt_for_interface():
        print(f"Using wireless interface without prompt: {selected}")
        set_interface(selected)
        return INTERFACE

    print("Available wireless interfaces:")
    for index, interface_name in enumerate(interfaces, start=1):
        default_label = " (default)" if interface_name == INTERFACE else ""
        print(f"  {index}. {interface_name}{default_label}")

    choice = input(
        f"Choose interface [1-{len(interfaces)}] or press Enter for {selected}: "
    ).strip()
    if not choice:
        print(f"Using interface: {selected}")
        set_interface(selected)
        return INTERFACE

    try:
        selected = interfaces[int(choice) - 1]
    except (ValueError, IndexError):
        selected = choice if choice in interfaces else _default_interface(interfaces)

    print(f"Using interface: {selected}")
    set_interface(selected)
    return INTERFACE
