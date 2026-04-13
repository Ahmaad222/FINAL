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
    get_uptime, get_raw_beacon, get_fingerprint
)
from core.event_bus import event_queue

# Session state
clients_map = {}
aps_state = {} 
START_TIME = time.time()
AP_TIMEOUT = 120 # Seconds to consider AP removed

# Deduplication Cache: {BSSID: last_sent_time}
seen_networks = {}
DEDUPE_COOLDOWN = 60 # Seconds
cache_lock = threading.Lock()

def enable_monitor_mode(iface):
    """Automatically enables monitor mode on the interface."""
    print(f"[MONITOR] 🔧 Enabling monitor mode on {iface}...")
    try:
        if os.name == 'nt':
            print("[MONITOR] Skipping monitor mode on Windows (not supported via raw commands).")
            return
            
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
    
    # Scapy signal strength depends on the adapter/platform
    signal = getattr(packet, "dBm_AntSignal", None)
    if signal is None:
        # Fallback for some platforms/drivers
        try:
            signal = -(256 - ord(packet.notdecoded[-4:-3]))
        except:
            signal = None

    # 🚀 Advanced Data Collection (Part 3 & 8)
    distance = estimate_distance(signal)
    auth = get_auth_type(packet)
    wps = get_wps_info(packet)
    manufacturer = get_manufacturer(bssid)
    uptime = get_uptime(packet)
    raw_beacon = get_raw_beacon(packet)
    fingerprint = get_fingerprint(packet)
    elapsed_time = round(time.time() - START_TIME, 2)

    clients = []
    if bssid in clients_map:
        for client_mac in clients_map[bssid]:
            clients.append({
                "mac": client_mac,
                "vendor": get_manufacturer(client_mac)
            })

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
        "fingerprint": fingerprint,
        "elapsed_time": elapsed_time,
        "clients": clients,
        "clients_count": len(clients)
    }


def handle_packet(packet):
    if not packet.haslayer(Dot11):
        return

    # [DEBUG] Packet captured (Part 7)
    # print("[DEBUG] Packet captured", flush=True)

    # Process Beacons and Probe Responses
    if packet.haslayer(Dot11Beacon) or packet.haslayer(Dot11ProbeResp):
        dot11 = packet[Dot11]
        if not dot11.addr2: return

        # [DEBUG] Parsed Network (Part 7)
        ssid = get_ssid(packet)
        # print(f"[DEBUG] Parsed SSID={ssid} BSSID={dot11.addr2}", flush=True)

        event = build_event(packet)
        bssid = event["bssid"]
        now = time.time()

        # 🛑 Deduplication Logic (Part 5)
        with cache_lock:
            last_sent = seen_networks.get(bssid, 0)
            if now - last_sent < DEDUPE_COOLDOWN:
                # Update current state but don't re-trigger event
                aps_state[bssid] = {
                    "last_seen": now,
                    "event": event
                }
                return 

            seen_networks[bssid] = now

        aps_state[bssid] = {
            "last_seen": now,
            "event": event
        }

        # Human readable output
        print(f"[PARSED] SSID={str(event['ssid']):<15} | BSSID={bssid} | CH={event['channel']} | SIG={event['signal']}")
        
        # [DEBUG] Data sent to backend (via event_queue -> ThreatManager -> WSClient)
        # print(f"[DEBUG] Enqueueing event for BSSID={bssid}", flush=True)
        event_queue.put(event)

    # Track Client Associations (Part 3)
    dot11 = packet[Dot11]
    # dot11.type 2 = Data frame, dot11.type 0 = Management
    if dot11.type == 2: # Data frame
        # addr1 = receiver, addr2 = transmitter, addr3 = BSSID (usually)
        bssid = dot11.addr3
        client = dot11.addr2
        
        # Simple heuristic to identify client-AP relationship
        if bssid and client and bssid != client and bssid != "ff:ff:ff:ff:ff:ff":
            if bssid in aps_state: # Only track if we know it's an AP
                clients_map.setdefault(bssid, set()).add(client)


def ap_cleaner():
    """Cleanup thread (Part 5)"""
    while True:
        now = time.time()
        
        # 1. Clear old entries from dedupe cache
        with cache_lock:
            for bssid in list(seen_networks.keys()):
                if now - seen_networks[bssid] > DEDUPE_COOLDOWN * 2:
                    del seen_networks[bssid]

        # 2. Clear timed out APs
        for bssid in list(aps_state.keys()):
            if now - aps_state[bssid]["last_seen"] > AP_TIMEOUT:
                print(f"[CLEANUP] Removing inactive AP: {bssid}")
                del aps_state[bssid]
                if bssid in clients_map:
                    del clients_map[bssid]
                
                event_queue.put({
                    "type": "AP_REMOVED",
                    "bssid": bssid
                })
        
        time.sleep(30)


def channel_hopper():
    print("[HOPPER] 🌀 Starting channel hopping (1-13)...")
    while True:
        if LOCKED_CHANNEL is not None:
            # os.system(f"iw dev {INTERFACE} set channel {LOCKED_CHANNEL}")
            time.sleep(1)
            continue

        for ch in range(1, 14):
            if LOCKED_CHANNEL is not None: break
            
            if os.name != 'nt':
                os.system(f"iw dev {INTERFACE} set channel {ch}")
            
            time.sleep(0.4)


def start_monitoring():
    # 🚀 Pre-flight checks
    if os.name != 'nt' and not os.path.exists(f"/sys/class/net/{INTERFACE}"):
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
        # Use conf.iface if provided
        sniff(iface=INTERFACE, prn=handle_packet, store=False)
    except Exception as e:
        print(f"[ERROR] Sniffing failed: {e}")
