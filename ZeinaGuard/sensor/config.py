# config.py
import os

# Default values - can be overridden by Environment variables
INTERFACE = os.getenv("SENSOR_INTERFACE", "wlx00e02b2d5191")
RUN_MODE = os.getenv("RUN_MODE", "LOCAL")

if RUN_MODE == "LOCAL":
    BACKEND_URL = "http://localhost:5000"
else:
    BACKEND_URL = "http://flask-backend:5000"

# Legacy support
BACKEND_HOST = "localhost" if "localhost" in BACKEND_URL else "flask-backend"
BACKEND_PORT = 5000

LOCKED_CHANNEL = None

TRUSTED_APS = {
    "WE_EDF20C": {
        "bssid": "20:E8:82:ED:F2:0C",
        "channel": 3 ,
        "encryption": "SECURED" }
}

ENABLE_ACTIVE_CONTAINMENT = os.getenv("ENABLE_CONTAINMENT", "True").lower() == "true"
DEAUTH_COUNT = int(os.getenv("DEAUTH_COUNT", "40"))
DEAUTH_INTERVAL = float(os.getenv("DEAUTH_INTERVAL", "0.1"))
