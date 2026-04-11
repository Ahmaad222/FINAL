# config.py
import os

# Default values - can be overridden by Environment Variables or CLI
INTERFACE = os.getenv("INTERFACE", "eth0")
BACKEND_HOST = os.getenv("BACKEND_HOST", "flask-backend")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "5000"))
BACKEND_URL = os.getenv("BACKEND_URL", f"http://{BACKEND_HOST}:{BACKEND_PORT}")

LOCKED_CHANNEL = None

TRUSTED_APS = {
    "WE_EDF20C": {
        "bssid": "20:E8:82:ED:F2:0C",
        "channel": 3 ,
        "encryption": "SECURED" }
}

ENABLE_ACTIVE_CONTAINMENT = os.getenv("ENABLE_ACTIVE_CONTAINMENT", "True").lower() == "true"
DEAUTH_COUNT = int(os.getenv("DEAUTH_COUNT", "40"))               # عدد الإطارات
DEAUTH_INTERVAL = float(os.getenv("DEAUTH_INTERVAL", "0.1"))              # زمن بين الإرسال

