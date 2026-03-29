from scapy.layers.dot11 import Dot11Elt, Dot11Beacon
import math
import binascii

# --------------------------------
# 🏢 Manufacturer OUI Lookup (Common)
# --------------------------------
OUI_MAP = {
    "00:0C:29": "VMware",
    "00:50:56": "VMware",
    "00:05:5D": "D-Link",
    "00:0D:88": "D-Link",
    "00:13:46": "D-Link",
    "00:17:9A": "D-Link",
    "00:19:5B": "D-Link",
    "00:1E:58": "D-Link",
    "00:21:91": "D-Link",
    "00:22:B0": "D-Link",
    "00:24:01": "D-Link",
    "00:26:5A": "D-Link",
    "1C:7E:E5": "D-Link",
    "C0:A0:BB": "D-Link",
    "00:0A:EB": "Cisco",
    "00:0B:85": "Cisco",
    "00:0C:30": "Cisco",
    "00:0D:BD": "Cisco",
    "00:0E:D7": "Cisco",
    "00:11:20": "Cisco",
    "00:11:BB": "Cisco",
    "00:12:00": "Cisco",
    "00:12:43": "Cisco",
    "00:12:7F": "Cisco",
    "00:13:19": "Cisco",
    "00:13:60": "Cisco",
    "00:13:C3": "Cisco",
    "00:13:C4": "Cisco",
    "00:14:1B": "Cisco",
    "00:14:69": "Cisco",
    "00:14:6A": "Cisco",
    "00:14:A8": "Cisco",
    "00:14:A9": "Cisco",
    "00:14:F1": "Cisco",
    "00:14:F2": "Cisco",
    "00:15:2B": "Cisco",
    "00:15:62": "Cisco",
    "00:15:63": "Cisco",
    "00:15:C5": "Cisco",
    "00:15:C6": "Cisco",
    "00:15:FA": "Cisco",
    "00:16:46": "Cisco",
    "00:16:47": "Cisco",
    "00:16:9D": "Cisco",
    "00:16:C7": "Cisco",
    "00:16:C8": "Cisco",
    "00:17:0E": "Cisco",
    "00:17:0F": "Cisco",
    "00:17:3B": "Cisco",
    "00:17:59": "Cisco",
    "00:17:5A": "Cisco",
    "00:17:94": "Cisco",
    "00:17:C4": "Cisco",
    "00:17:DF": "Cisco",
    "00:17:E0": "Cisco",
    "00:18:18": "Cisco",
    "00:18:19": "Cisco",
    "00:18:73": "Cisco",
    "00:18:74": "Cisco",
    "00:18:B9": "Cisco",
    "00:18:BA": "Cisco",
    "00:19:07": "Cisco",
    "00:19:08": "Cisco",
    "00:19:2F": "Cisco",
    "00:19:30": "Cisco",
    "00:19:55": "Cisco",
    "00:19:56": "Cisco",
    "00:19:AA": "Cisco",
    "00:19:AB": "Cisco",
    "00:19:E7": "Cisco",
    "00:19:E8": "Cisco",
    "00:1A:2F": "Cisco",
    "00:1A:30": "Cisco",
    "00:1A:6C": "Cisco",
    "00:1A:6D": "Cisco",
    "00:1A:A1": "Cisco",
    "00:1A:A2": "Cisco",
    "00:1B:0C": "Cisco",
    "00:1B:0D": "Cisco",
    "00:1B:2A": "Cisco",
    "00:1B:2B": "Cisco",
    "00:1B:53": "Cisco",
    "00:1B:54": "Cisco",
    "00:1B:8F": "Cisco",
    "00:1B:90": "Cisco",
    "00:1B:D4": "Cisco",
    "00:1B:D5": "Cisco",
    "00:1C:0E": "Cisco",
    "00:1C:0F": "Cisco",
    "00:1C:57": "Cisco",
    "00:1C:58": "Cisco",
    "00:1C:B0": "Cisco",
    "00:1C:B1": "Cisco",
    "00:1D:45": "Cisco",
    "00:1D:46": "Cisco",
    "00:1D:70": "Cisco",
    "00:1D:71": "Cisco",
    "00:1D:A1": "Cisco",
    "00:1D:A2": "Cisco",
    "00:1D:E5": "Cisco",
    "00:1D:E6": "Cisco",
    "00:1E:13": "Cisco",
    "00:1E:14": "Cisco",
    "00:1E:49": "Cisco",
    "00:1E:4A": "Cisco",
    "00:1E:79": "Cisco",
    "00:1E:7A": "Cisco",
    "00:1E:BE": "Cisco",
    "00:1E:BF": "Cisco",
    "00:1E:F6": "Cisco",
    "00:1E:F7": "Cisco",
    "00:1F:26": "Cisco",
    "00:1F:27": "Cisco",
    "00:1F:6C": "Cisco",
    "00:1F:6D": "Cisco",
    "00:1F:9D": "Cisco",
    "00:1F:9E": "Cisco",
    "00:1F:CA": "Cisco",
    "00:1F:CB": "Cisco",
    "00:21:1B": "Cisco",
    "00:21:1C": "Cisco",
    "00:21:55": "Cisco",
    "00:21:56": "Cisco",
    "00:21:A0": "Cisco",
    "00:21:A1": "Cisco",
    "00:21:D7": "Cisco",
    "00:21:D8": "Cisco",
    "00:22:55": "Cisco",
    "00:22:56": "Cisco",
    "00:22:90": "Cisco",
    "00:22:91": "Cisco",
    "00:22:BD": "Cisco",
    "00:22:BE": "Cisco",
    "00:23:04": "Cisco",
    "00:23:05": "Cisco",
    "00:23:33": "Cisco",
    "00:23:34": "Cisco",
    "00:23:5D": "Cisco",
    "00:23:5E": "Cisco",
    "00:23:99": "Cisco",
    "00:23:9A": "Cisco",
    "00:23:EB": "Cisco",
    "00:23:EC": "Cisco",
    "00:24:13": "Cisco",
    "00:24:14": "Cisco",
    "00:24:50": "Cisco",
    "00:24:51": "Cisco",
    "00:24:97": "Cisco",
    "00:24:98": "Cisco",
    "00:24:C3": "Cisco",
    "00:24:C4": "Cisco",
    "00:24:F7": "Cisco",
    "00:24:F8": "Cisco",
    "00:25:45": "Cisco",
    "00:25:46": "Cisco",
    "00:25:83": "Cisco",
    "00:25:84": "Cisco",
    "00:25:B4": "Cisco",
    "00:25:B5": "Cisco",
    "00:26:0A": "Cisco",
    "00:26:0B": "Cisco",
    "00:26:51": "Cisco",
    "00:26:52": "Cisco",
    "00:26:98": "Cisco",
    "00:26:99": "Cisco",
    "00:26:CB": "Cisco",
    "00:26:CC": "Cisco",
    "00:14:6C": "Netgear",
    "00:18:4D": "Netgear",
    "00:1B:2F": "Netgear",
    "00:1E:2A": "Netgear",
    "00:1F:33": "Netgear",
    "00:22:3F": "Netgear",
    "00:24:B2": "Netgear",
    "00:26:F2": "Netgear",
    "20:4E:7F": "Netgear",
    "2C:30:33": "Netgear",
    "00:1D:0F": "TP-Link",
    "00:21:27": "TP-Link",
    "00:23:CD": "TP-Link",
    "00:25:86": "TP-Link",
    "30:B5:C2": "TP-Link",
    "50:C7:BF": "TP-Link",
    "60:E3:27": "TP-Link",
    "70:4F:57": "TP-Link",
    "74:EA:3A": "TP-Link",
    "78:44:76": "TP-Link",
    "84:16:F9": "TP-Link",
    "94:0C:6D": "TP-Link",
    "A8:40:41": "TP-Link",
    "B0:48:7A": "TP-Link",
    "C0:4A:00": "TP-Link",
    "C4:6E:1F": "TP-Link",
    "D8:5D:4C": "TP-Link",
    "E8:94:F6": "TP-Link",
    "F4:F2:6D": "TP-Link",
    "00:03:7F": "Atheros",
    "00:13:74": "Atheros",
    "00:1C:10": "Atheros",
    "00:1D:6E": "Atheros",
    "00:26:5E": "Atheros",
    "00:0E:8E": "ASUS",
    "00:15:AF": "ASUS",
    "00:1B:FC": "ASUS",
    "00:1E:8C": "ASUS",
    "00:23:54": "ASUS",
    "00:26:18": "ASUS",
    "08:60:6E": "ASUS",
    "14:DD:A9": "ASUS",
    "1C:B7:2C": "ASUS",
    "24:0A:64": "ASUS",
    "30:85:A9": "ASUS",
    "38:2C:4A": "ASUS",
    "40:16:7E": "ASUS",
    "50:46:5D": "ASUS",
    "54:A0:50": "ASUS",
    "60:45:CB": "ASUS",
    "60:A4:4C": "ASUS",
    "74:D0:2B": "ASUS",
    "AC:22:0B": "ASUS",
    "BC:EE:7B": "ASUS",
    "D8:50:E6": "ASUS",
    "F0:79:59": "ASUS",
}

def get_ssid(packet):
    elt = packet.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 0:
            try:
                ssid = elt.info.decode(errors="ignore").strip()
                return ssid if ssid else "Hidden"
            except:
                return "Hidden"
        elt = elt.payload.getlayer(Dot11Elt)
    return "Hidden"


def extract_channel(packet):
    elt = packet.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 3:
            try:
                if elt.info:
                    return int(elt.info[0])
            except:
                pass 
        elt = elt.payload.getlayer(Dot11Elt)
    return None

def estimate_distance(pwr):
    """Estimates distance in meters based on signal strength (dBm)."""
    if pwr is None:
        return -1
    # Simple free-space path loss model approximation
    # d = 10 ^ ((27.55 - (20 * log10(freq)) + |pwr|) / 20)
    # Using a simplified formula for 2.4GHz: d = 10 ^ ((abs(pwr) - 40) / 20)
    try:
        dist = 10 ** ((abs(pwr) - 40) / 20)
        return round(dist, 2)
    except:
        return -1

def get_auth_type(packet):
    """Parses RSN and WPA elements to determine authentication type."""
    cap = packet.getlayer(Dot11Beacon).cap
    elt = packet.getlayer(Dot11Elt)

    auth = "OPEN"
    if cap.privacy:
        auth = "WEP" # Default if privacy is set but no RSN/WPA

    while elt:
        if elt.ID == 48: # RSN (WPA2/WPA3)
            auth = "WPA2"
            if "WPA3" in str(elt.info): # Simplistic check
                auth = "WPA3"
        elif elt.ID == 221: # Vendor Specific
            if elt.info.startswith(b'\x00P\xf2\x01\x01\x00'): # WPA
                auth = "WPA"
        elt = elt.payload.getlayer(Dot11Elt)
    return auth

def get_wps_info(packet):
    """Checks for WPS information in vendor-specific elements."""
    elt = packet.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 221: # Vendor Specific
            if elt.info.startswith(b'\x00P\xf2\x04'): # WPS OUI
                return "V1.0 (PBC/PIN)" # Simplified WPS detection
        elt = elt.payload.getlayer(Dot11Elt)
    return "N/A"

def get_manufacturer(mac):
    """Looks up manufacturer name from MAC OUI."""
    if not mac:
        return "Unknown"
    oui = mac.upper()[:8]
    return OUI_MAP.get(oui, "Unknown")

def get_uptime(packet):
    """Estimates uptime from the Beacon timestamp field (in microseconds)."""
    try:
        timestamp = packet.getlayer(Dot11Beacon).timestamp
        seconds = timestamp / 1000000
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{days}d {hours}h {minutes}m"
    except:
        return "Unknown"

def get_raw_beacon(packet):
    """Returns the raw hex of the beacon frame."""
    try:
        return binascii.hexlify(bytes(packet)).decode()[:100] + "..." # Truncated for efficiency
    except:
        return ""