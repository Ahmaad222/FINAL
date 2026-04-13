from scapy.layers.dot11 import Dot11Elt, Dot11Beacon
import math
import binascii
from mac_vendor_lookup import MacLookup

# Initialize MacLookup (it will download the vendor list if not present)
try:
    mac_lookup = MacLookup()
    # mac_lookup.update_vendors() # Optional: call this to update the local database
except Exception:
    mac_lookup = None

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
    """
    Estimates distance in meters based on signal strength (dBm).
    Formula: distance = 10 ^ ((txPower - signal) / (10 * n))
    txPower ≈ -40, n ≈ 3 (indoor)
    """
    if pwr is None:
        return -1
    
    txPower = -40
    n = 3
    try:
        # distance = 10 ** ((txPower - pwr) / (10 * n))
        # Note: Scapy pwr is typically negative (e.g., -60)
        dist = 10 ** ((txPower - pwr) / (10 * n))
        return round(dist, 2)
    except Exception:
        return -1

def get_auth_type(packet):
    """Parses RSN and WPA elements to determine authentication type."""
    if not packet.haslayer(Dot11Beacon):
        return "Unknown"
        
    cap = packet.getlayer(Dot11Beacon).cap
    elt = packet.getlayer(Dot11Elt)

    auth = "OPEN"
    if cap.privacy:
        auth = "WEP" # Default if privacy is set but no RSN/WPA

    while elt:
        if elt.ID == 48: # RSN (WPA2/WPA3)
            auth = "WPA2"
            # More detailed check for WPA3
            if hasattr(elt, 'info') and b'\x01\x00\x00\x0f\xac\x04' in elt.info: # SAE (WPA3)
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
    """Looks up manufacturer name from MAC OUI using mac-vendor-lookup."""
    if not mac or mac == "ff:ff:ff:ff:ff:ff":
        return "Unknown"
    
    if mac_lookup:
        try:
            return mac_lookup.lookup(mac)
        except Exception:
            return "Unknown"
    return "Unknown"

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
    """Returns the raw hex of the beacon frame summary or hash."""
    try:
        # Return first 100 bytes of raw packet as hex
        return binascii.hexlify(bytes(packet)).decode()[:100]
    except:
        return ""

def get_fingerprint(packet):
    """Creates a unique fingerprint for an AP based on certain fields."""
    import hashlib
    try:
        bssid = packet.addr2
        ssid = get_ssid(packet)
        # Combine BSSID, SSID and some capability bits for a fingerprint
        raw_data = f"{bssid}|{ssid}|{packet.cap}"
        return hashlib.md5(raw_data.encode()).hexdigest()
    except:
        return "N/A"
