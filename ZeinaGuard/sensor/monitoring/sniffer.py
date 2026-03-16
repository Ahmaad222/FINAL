# monitoring/sniffer.py

from scapy.all import sniff
from scapy.layers.dot11 import Dot11, Dot11Beacon
import threading
import os
import time
import datetime

from config import INTERFACE, LOCKED_CHANNEL
from utils import get_ssid, extract_channel
from core.event_bus import event_queue

clients_map = {}  # {bssid: set(client_macs)}

def is_open_network(packet):
    if packet.haslayer(Dot11Beacon):
        cap = packet[Dot11Beacon].cap
        return not cap.privacy
    return False

def build_event(packet):
    dot11 = packet[Dot11]

    bssid = dot11.addr2
    ssid = get_ssid(packet)
    channel = extract_channel(packet)
    signal = getattr(packet, "dBm_AntSignal", None)

    clients_count = len(clients_map.get(bssid, set()))

    return {
        # 🚀 التعديل هنا عشان الداتا تتبعت للـ Dashboard بدون مشاكل
        "timestamp": datetime.datetime.now().isoformat(),
        "bssid": bssid,
        "ssid": ssid,
        "channel": channel,
        "signal": signal,
        "encryption": "OPEN" if is_open_network(packet) else "SECURED",
        "clients": clients_count
    }

def handle_packet(packet):
    if not packet.haslayer(Dot11):
        return

    dot11 = packet[Dot11]

    # Beacon (Access Point discovery)
    if packet.haslayer(Dot11Beacon) and dot11.addr2:
        event = build_event(packet)
        print(f"📡 AP Found: {event['ssid']} | {event['bssid']} | CH {event['channel']}")
        event_queue.put(event)

    # Data frames (Client ↔ AP)
    if dot11.type == 2:
        bssid = dot11.addr3
        src = dot11.addr2

        if bssid and src and bssid != src:
            clients_map.setdefault(bssid, set()).add(src)

def channel_hopper():
    import config

    while True:
        # لو فيه channel مقفول عليه
        if config.LOCKED_CHANNEL is not None:
            os.system(f"iwconfig {INTERFACE} channel {config.LOCKED_CHANNEL}")
            time.sleep(1)
            continue

        # لو مفيش lock نكمل hopping
        for ch in range(1, 14):
            if config.LOCKED_CHANNEL is not None:
                break

            os.system(f"iwconfig {INTERFACE} channel {ch}")
            time.sleep(0.4)

def start_monitoring():
    hopper = threading.Thread(target=channel_hopper)
    hopper.daemon = True
    hopper.start()

    sniff(iface=INTERFACE, prn=handle_packet, store=False)