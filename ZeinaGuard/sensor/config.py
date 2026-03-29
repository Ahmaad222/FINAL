# config.py

# Default values - can be overridden by CLI or runtime logic
INTERFACE = "wlx002e2dc0346b"
BACKEND_HOST = "192.168.201.130"
BACKEND_PORT = 8000

LOCKED_CHANNEL = None

TRUSTED_APS = {
    "WE_EDF20C": {
        "bssid": "20:E8:82:ED:F2:0C",
        "channel": 3 ,
        "encryption": "SECURED" }
}

ENABLE_ACTIVE_CONTAINMENT = True   
DEAUTH_COUNT = 40               # عدد الإطارات
DEAUTH_INTERVAL = 0.1              # زمن بين الإرسال

