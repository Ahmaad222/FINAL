# monitoring/sniffer.py

from scapy.all import sniff, conf
from scapy.layers.dot11 import Dot11, Dot11Beacon
import threading
import os
import sys
import time
import datetime

from config import INTERFACE, LOCKED_CHANNEL
from utils import (
    get_ssid, extract_channel, estimate_distance, 
    get_auth_type, get_wps_info, get_manufacturer, 
    get_uptime, get_raw_beacon
)
from core.event_bus import event_queue

clients_map = {}
aps_state = {} 

AP_TIMEOUT = 60 
START_TIME = time.time()
FIRST_PACKET = True

def is_open_network(packet):
    if packet.haslayer(Dot11Beacon):
        cap = packet[Dot11Beacon].cap
        return not cap.privacy
    return False


def build_event(packet):
    global FIRST_PACKET
    if FIRST_PACKET:
        print("🎯 First WiFi packet captured! Sniffer is working.")
        FIRST_PACKET = False

    dot11 = packet[Dot11]

    bssid = dot11.addr2
    ssid = get_ssid(packet)
    channel = extract_channel(packet)
    signal = getattr(packet, "dBm_AntSignal", None)

    # 🚀 Advanced Data Collection
    distance = estimate_distance(signal)
    auth = get_auth_type(packet)
    wps = get_wps_info(packet)
    manufacturer = get_manufacturer(bssid)
    uptime = get_uptime(packet)
    raw_beacon = get_raw_beacon(packet)
    elapsed_time = round(time.time() - START_TIME, 2)

    clients_count = len(clients_map.get(bssid, set()))

    return {
        "timestamp": datetime.datetime.now().isoformat(),
        "bssid": bssid,
        "ssid": ssid,
        "channel": channel,
        "signal": signal,
        "distance": distance,
        "auth": auth,
        "wps": wps,
        "manufacturer": manufacturer,
        "uptime": uptime,
        "raw_beacon": raw_beacon,
        "elapsed_time": elapsed_time,
        "encryption": "OPEN" if is_open_network(packet) else "SECURED",
        "clients": clients_count
    }


def handle_packet(packet):
    if not packet.haslayer(Dot11):
        return

    dot11 = packet[Dot11]

    if packet.haslayer(Dot11Beacon) and dot11.addr2:

        event = build_event(packet)
        bssid = event["bssid"]
        now = time.time()

        aps_state[bssid] = {
            "last_seen": now,
            "event": event
        }

        event_queue.put(event)

    if dot11.type == 2:
        bssid = dot11.addr3
        src = dot11.addr2

        if bssid and src and bssid != src:
            clients_map.setdefault(bssid, set()).add(src)


def ap_cleaner():
    while True:
        now = time.time()
        removed = []

        for bssid in list(aps_state.keys()):
            if now - aps_state[bssid]["last_seen"] > AP_TIMEOUT:
                removed.append(bssid)
                del aps_state[bssid]

                event_queue.put({
                    "type": "AP_REMOVED",
                    "bssid": bssid
                })

        time.sleep(5)


def channel_hopper():
    import config

    while True:
        if config.LOCKED_CHANNEL is not None:
            os.system(f"iwconfig {INTERFACE} channel {config.LOCKED_CHANNEL} 2>/dev/null")
            time.sleep(1)
            continue

        for ch in range(1, 14):
            if config.LOCKED_CHANNEL is not None:
                break

            os.system(f"iwconfig {INTERFACE} channel {ch} 2>/dev/null")
            time.sleep(0.4)


def start_monitoring():
    # 🚀 Pre-flight checks
    if not os.path.exists(f"/sys/class/net/{INTERFACE}"):
        print(f"❌ Error: Interface {INTERFACE} not found!")
        return

    if os.name != 'nt' and os.geteuid() != 0:
        print("❌ Error: Root privileges required for sniffing!")
        return

    threading.Thread(target=channel_hopper, daemon=True).start()
    threading.Thread(target=ap_cleaner, daemon=True).start()

    print(f"📡 Sniffing on {INTERFACE}...")
    try:
        sniff(iface=INTERFACE, prn=handle_packet, store=False)
    except Exception as e:
        print(f"❌ Sniffing failed: {e}")