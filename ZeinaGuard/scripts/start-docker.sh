#!/bin/bash

echo "[SYSTEM] Starting Docker services..."

# Detect docker compose version
if docker compose version > /dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

$COMPOSE up -d

echo "[SYSTEM] Waiting for backend to be fully ready..."

# Wait for backend health (strong check)
for i in {1..30}; do
    RESPONSE=$(curl -s http://localhost:5000/health)

    if echo "$RESPONSE" | grep -q "healthy"; then
        echo "[SYSTEM] Backend is ready!"
        break
    fi

    echo "Waiting for backend... ($i/30)"
    sleep 2
done

# Final safety check
if ! curl -s http://localhost:5000/health | grep -q "healthy"; then
    echo "[ERROR] Backend failed to start correctly!"
    $COMPOSE logs flask-backend
    exit 1
fi

echo "[SYSTEM] Starting sensor locally..."

# Absolute path fix (IMPORTANT)
PROJECT_ROOT=$(pwd)
SENSOR_PATH="$PROJECT_ROOT/sensor"

# Function to run sensor
run_sensor() {
    cd "$SENSOR_PATH" || exit
    export RUN_MODE=LOCAL
    export ENABLE_TUI=True

    echo "[SENSOR] Running on interface: wlx002e2dc0346b"
    sudo python3 main.py wlx002e2dc0346b
}

# Try to run in new terminal
if command -v gnome-terminal > /dev/null 2>&1; then
    echo "[SYSTEM] Launching sensor in new terminal..."

    gnome-terminal -- bash -c "
    cd '$SENSOR_PATH';
    export RUN_MODE=LOCAL;
    export ENABLE_TUI=True;
    echo '[SENSOR] Starting ZeinaGuard Sensor...';
    sudo python3 main.py wlx002e2dc0346b;
    echo '[SENSOR] Stopped.';
    exec bash
    "

else
    echo "[SYSTEM] gnome-terminal not found → running in same terminal"
    run_sensor
fi