from scapy.layers.dot11 import Dot11Elt

def get_ssid(packet):
    elt = packet.getlayer(Dot11Elt)
    while elt:
        if elt.ID == 0:
            try:
                # بنفك التشفير بتاع الاسم
                ssid = elt.info.decode(errors="ignore").strip()
                # لو الاسم فاضي (شبكة مخفية) أو كله مسافات، نرجع Hidden
                return ssid if ssid else "Hidden"
            except:
                return "Hidden"
        elt = elt.payload.getlayer(Dot11Elt)
    return "Hidden"


def extract_channel(packet):
    elt = packet.getlayer(Dot11Elt)
    while elt:
        # ID 3 هو الـ DS Parameter Set اللي جواه رقم القناة في الـ 2.4GHz
        if elt.ID == 3:
            try:
                if elt.info:
                    return int(elt.info[0])
            except:
                pass # لو حصل أي مشكلة كمل تدوير
        elt = elt.payload.getlayer(Dot11Elt)
    return None