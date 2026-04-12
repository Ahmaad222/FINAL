# monitoring/sniffer.py

from scapy.all import sniff, conf
from scapy.layers.dot11 import Dot11, Dot11Beacon, Dot11ProbeResp
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

# Deduplication Cache: {BSSID: last_sent_time}
seen_networks = {}
DEDUPE_COOLDOWN = 60 # Seconds
cache_lock = threading.Lock()

def enable_monitor_mode(iface):
    """Automatically enables monitor mode on the interface."""
    print(f"[MONITOR] 🔧 Enabling monitor mode on {iface}...")
    try:
        os.system(f"ip link set {iface} down")
        os.system(f"iw dev {iface} set type monitor")
        os.system(f"ip link set {iface} up")
        print(f"[MONITOR] ✅ Monitor mode enabled on {iface}")
    except Exception as e:
        print(f"[MONITOR] ❌ Failed to enable monitor mode: {e}")

def build_event(packet):
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

    # Process Beacons and Probe Responses
    if packet.haslayer(Dot11Beacon) or packet.haslayer(Dot11ProbeResp):
        dot11 = packet[Dot11]
        if not dot11.addr2: return

        event = build_event(packet)
        bssid = event["bssid"]
        now = time.time()

        # 🛑 Deduplication Logic
        with cache_lock:
            last_sent = seen_networks.get(bssid, 0)
            # If seen in last 60 seconds, don't resend (unless it's a critical update we want, but let's stick to 60s)
            if now - last_sent < DEDUPE_COOLDOWN:
                return 

            seen_networks[bssid] = now

        aps_state[bssid] = {
            "last_seen": now,
            "event": event
        }

        print(f"[PARSED] SSID={str(event['ssid']):<15} | BSSID={bssid} | CH={event['channel']} | SIG={event['signal']}")
        event_queue.put(event)

    dot11 = packet[Dot11]
    if dot11.type == 2: # Data frame
        bssid = dot11.addr3
        src = dot11.addr2
        if bssid and src and bssid != src:
            clients_map.setdefault(bssid, set()).add(src)


def ap_cleaner():
    while True:
        now = time.time()
        with cache_lock:
            # Clear old entries from dedupe cache every few mins to keep memory clean
            for bssid in list(seen_networks.keys()):
                if now - seen_networks[bssid] > DEDUPE_COOLDOWN * 2:
                    del seen_networks[bssid]

        for bssid in list(aps_state.keys()):
            if now - aps_state[bssid]["last_seen"] > AP_TIMEOUT:
                del aps_state[bssid]
                event_queue.put({
                    "type": "AP_REMOVED",
                    "bssid": bssid
                })
        time.sleep(10)


def channel_hopper():
    print("[HOPPER] 🌀 Starting channel hopping (1-13)...")
    while True:
        if LOCKED_CHANNEL is not None:
            os.system(f"iw dev {INTERFACE} set channel {LOCKED_CHANNEL}")
            time.sleep(1)
            continue

        for ch in range(1, 14):
            if LOCKED_CHANNEL is not None: break
            os.system(f"iw dev {INTERFACE} set channel {ch}")
            time.sleep(0.4)


def start_monitoring():
    # 🚀 Pre-flight checks
    if not os.path.exists(f"/sys/class/net/{INTERFACE}"):
        print(f"❌ Error: Interface {INTERFACE} not found!")
        return

    if os.name != 'nt' and os.geteuid() != 0:
        print("❌ Error: Root privileges required for sniffing!")
        return

    # Enable monitor mode automatically
    enable_monitor_mode(INTERFACE)

    threading.Thread(target=channel_hopper, daemon=True).start()
    threading.Thread(target=ap_cleaner, daemon=True).start()

    print(f"📡 Sniffing on {INTERFACE} (Monitor Mode)...")
    try:
        sniff(iface=INTERFACE, prn=handle_packet, store=False)
    except Exception as e:
        print(f"[ERROR] Sniffing failed: {e}")