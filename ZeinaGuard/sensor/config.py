# config.py
import os

# Default values - can be overridden by Environment Variables or CLI
INTERFACE = os.getenv("INTERFACE", "wlx002e2dc0346b") # Real wireless interface from user
BACKEND_HOST = os.getenv("BACKEND_HOST", "flask-backend")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "5000"))

# Automatic Backend Resolution
if os.getenv("BACKEND_URL"):
    BACKEND_URL = os.getenv("BACKEND_URL")
elif os.getenv("RUN_MODE") == "LOCAL":
    BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
else:
    # Default to container name, but fallback to localhost if resolution fails
    BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

print(f"[CONFIG] 🔗 Backend URL: {BACKEND_URL}")

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

# --- UI & Logging Configuration ---
RUN_MODE = os.getenv("RUN_MODE", "DOCKER").upper() # DOCKER | LOCAL
# If in Docker, default TUI to False unless explicitly enabled
ENABLE_TUI = os.getenv("ENABLE_TUI", "False" if RUN_MODE == "DOCKER" else "True").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

