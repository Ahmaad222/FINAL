from scapy.layers.dot11 import Dot11Elt, Dot11Beacon
import math
import binascii
import hashlib
from mac_vendor_lookup import MacLookup

# --------------------------------
# 🏢 Manufacturer Lookup (Advanced)
# --------------------------------
mac_lookup = MacLookup()
# Try to update the vendor list, but don't fail if offline
try:
    mac_lookup.update_vendors()
except:
    pass

def get_manufacturer(mac):
    """Looks up manufacturer name from MAC address using mac-vendor-lookup."""
    if not mac:
        return "Unknown"
    try:
        return mac_lookup.lookup(mac)
    except:
        return "Unknown"

# --------------------------------
# 🧬 Biometric Fingerprinting
# --------------------------------
def get_ap_fingerprint(packet):
    """Generates a unique biometric fingerprint for an AP based on specific IE fields."""
    try:
        # Extract specific elements that don't change often
        # (Beacons, capabilities, supported rates)
        raw_data = bytes(packet[Dot11Beacon])
        return hashlib.sha256(raw_data).hexdigest()[:16]
    except:
        return "N/A"

# --------------------------------
# 📡 WiFi Metrics
# --------------------------------
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
    # Simple free-space path loss model approximation for 2.4GHz: d = 10 ^ ((abs(pwr) - 40) / 20)
    try:
        dist = 10 ** ((abs(pwr) - 40) / 20)
        return round(dist, 2)
    except:
        return -1

def get_auth_type(packet):
    """Parses RSN and WPA elements to determine authentication type."""
    try:
        cap = packet.getlayer(Dot11Beacon).cap
        elt = packet.getlayer(Dot11Elt)

        auth = "OPEN"
        if cap.privacy:
            auth = "WEP" # Default if privacy is set but no RSN/WPA

        while elt:
            if elt.ID == 48: # RSN (WPA2/WPA3)
                auth = "WPA2"
                # Check for WPA3 (SAE)
                if b'\x08' in bytes(elt.info): # Simplistic SAE check
                    auth = "WPA3"
            elif elt.ID == 221: # Vendor Specific
                if elt.info.startswith(b'\x00P\xf2\x01\x01\x00'): # WPA
                    auth = "WPA"
            elt = elt.payload.getlayer(Dot11Elt)
        return auth
    except:
        return "UNKNOWN"

def get_wps_info(packet):
    """Checks for WPS information in vendor-specific elements."""
    elt = packet.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 221: # Vendor Specific
            if elt.info.startswith(b'\x00P\xf2\x04'): # WPS OUI
                return "V1.0 (PBC/PIN)" # Simplified WPS detection
        elt = elt.payload.getlayer(Dot11Elt)
    return "N/A"

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
        return binascii.hexlify(bytes(packet)).decode()[:100] + "..." # Truncated
    except:
        return ""

def is_open_network(packet):
    """Returns True if the network is Open (no encryption)."""
    try:
        return not packet.getlayer(Dot11Beacon).cap.privacy
    except:
        return True
