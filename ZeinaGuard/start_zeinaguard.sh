#!/usr/bin/env bash
set -euo pipefail

# ==========================================
# ZeinaGuard Pro - Master Execution Script 
# (Auto-Healing & Pre-flight checks included)
# ==========================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
WIFI_INTERFACE="${1:-wlp0s20f3}" # الكارت الافتراضي

mkdir -p "$LOG_DIR"

echo -e "\n🚀 [ZeinaGuard] Starting System Initialization...\n"

# ------------------------------------------
# Cleanup & Exit Trap (مضاد للأعطال)
# ------------------------------------------
cleanup() {
    echo -e "\n\n🛑 [ZeinaGuard] Shutting down all services or handling error..."
    kill $(jobs -p) 2>/dev/null || true
    echo "🔄 Restoring network interface to Managed Mode..."
    sudo airmon-ng stop "${WIFI_INTERFACE}mon" 2>/dev/null || true
    sudo systemctl restart NetworkManager
    echo "✅ [ZeinaGuard] Cleanup complete. Internet restored!"
    exit 0
}
# الـ ERR تضمن إن لو أي خطوة فشلت، يرجعلك النت فوراً
trap cleanup SIGINT SIGTERM ERR

# ------------------------------------------
# 0. Pre-flight: Install Dependencies (Internet needed)
# ------------------------------------------
echo "[0/5] 📦 Checking and Installing Dependencies (Internet needed)..."

# نطلب صلاحية الـ sudo مقدماً عشان ميعلقش في الخلفية
sudo -v

# أ. تجهيز الباك إند
echo "⏳ [Backend] Checking environment and requirements..."
cd "$ROOT_DIR/backend"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt > "$LOG_DIR/backend_install.log" 2>&1
deactivate

# ب. تجهيز السنسور
echo "⏳ [Sensor] Bootstrapping environment..."
cd "$ROOT_DIR/sensor"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
# بنشغل دالة التسطيب بس من غير توجيه اللوج عشان لو فيه Error يظهرلك
../backend/.venv/bin/python3 -c "from main import ensure_virtualenv; ensure_virtualenv()"

echo "✅ All dependencies are installed and cached."

# ------------------------------------------
# 1. Network Preparation (Kills Internet)
# ------------------------------------------
echo "[1/5] 📡 Preparing Wireless Interface ($WIFI_INTERFACE)..."
if ! command -v airmon-ng &> /dev/null; then
    echo "❌ ERROR: airmon-ng is not installed."
    exit 1
fi

sudo airmon-ng check kill
sudo airmon-ng start "$WIFI_INTERFACE"
MONITOR_INTERFACE="${WIFI_INTERFACE}mon"
echo "✅ Interface is now in Monitor Mode: $MONITOR_INTERFACE"

# ------------------------------------------
# 2. Start Backend
# ------------------------------------------
echo "[2/5] ⚙️ Starting Backend Server (Port 5000)..."
cd "$ROOT_DIR/backend"
source .venv/bin/activate
gunicorn --worker-class eventlet --bind 0.0.0.0:5000 app:app > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

echo "⏳ Waiting for backend to be ready..."
while ! nc -z 127.0.0.1 5000 2>/dev/null; do   
  sleep 1
done
echo "✅ Backend is UP!"

# ------------------------------------------
# 3. Start Frontend
# ------------------------------------------
echo "[3/5] 🖥️ Starting Next.js Frontend (Port 3000)..."
cd "$ROOT_DIR"
pnpm dev > "$LOG_DIR/frontend.log" 2>&1 &

echo "⏳ Waiting for frontend to be ready..."
while ! nc -z 127.0.0.1 3000 2>/dev/null; do   
  sleep 1
done
echo "✅ Frontend is UP! (http://localhost:3000)"

# ------------------------------------------
# 4. Start Sensor (Root Privileges)
# ------------------------------------------
echo "[4/5] 🛡️ Starting Sensor on $MONITOR_INTERFACE..."
cd "$ROOT_DIR/sensor"
SENSOR_PYTHON="$ROOT_DIR/sensor/.venv/bin/python"

# تشغيل السنسور وربطه بالباك إند
sudo -E env "BACKEND_URL=http://localhost:5000" "$SENSOR_PYTHON" main.py --interface "$MONITOR_INTERFACE"
