# config.py

INTERFACE = "wlx002e2dc0346b"

LOCKED_CHANNEL = None

TRUSTED_APS = {
    "WE_EDF20C": {
        "bssid": "20:e8:82:ed:f2:0c",
        "channel": 1 ,
        "encryption": "SECURED" }
}

ENABLE_ACTIVE_CONTAINMENT = True   
DEAUTH_COUNT = 40               # عدد الإطارات
DEAUTH_INTERVAL = 0.1              # زمن بين الإرسال

