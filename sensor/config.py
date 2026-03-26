# config.py

INTERFACE = "wlx002e2dc0346b"

LOCKED_CHANNEL = None

TRUSTED_APS = {
    "Orange-RoQa": {
        "bssid": "1E:3C:D4:2A:3C:1C",
        "channel": 7 ,
        "encryption": "SECURED" }
}

ENABLE_ACTIVE_CONTAINMENT = True   
DEAUTH_COUNT = 40               # عدد الإطارات
DEAUTH_INTERVAL = 0.1              # زمن بين الإرسال

