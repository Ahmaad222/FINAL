#!/bin/bash

# ZeinaGuard Hybrid Startup Script
# Starts Backend in Docker and Sensor Locally

echo "[SYSTEM] Starting Docker services..."

# Use 'docker compose' or 'docker-compose'
if docker compose version > /dev/null 2>&1; then
    COMPOSE="docker compose"
else
    COMPOSE="docker-compose"
fi

$COMPOSE up -d

echo "[SYSTEM] Waiting for backend..."

# wait until backend is ready
MAX_RETRIES=30
RETRIES=0
until curl -s http://localhost:5000/health > /dev/null; do
    echo "Waiting for backend... ($RETRIES/$MAX_RETRIES)"
    sleep 2
    ((RETRIES++))
    if [ $RETRIES -ge $MAX_RETRIES ]; then
        echo "[ERROR] Backend failed to start in time."
        $COMPOSE logs flask-backend
        exit 1
    fi
done

echo "[SYSTEM] Backend is ready!"

# Final verification
if ! curl -s http://localhost:5000/health | grep -q "healthy"; then
    echo "[ERROR] Backend health check failed."
    exit 1
fi

echo "[SYSTEM] Starting sensor locally..."

# Function to run sensor
run_sensor() {
    cd sensor || exit
    export RUN_MODE=LOCAL
    export ENABLE_TUI=True
    # Using the interface specified by the user
    sudo python3 main.py wlx002e2dc0346b
}

# Try to run in a new terminal for better UX if gnome-terminal is available
if command -v gnome-terminal > /dev/null 2>&1; then
    gnome-terminal -- bash -c "
    cd $(pwd)/sensor;
    export RUN_MODE=LOCAL;
    export ENABLE_TUI=True;
    echo 'Starting ZeinaGuard Sensor in new terminal...';
    sudo python3 main.py wlx002e2dc0346b;
    exec bash
    "
    echo "[SYSTEM] Sensor started in a new terminal."
else
    echo "[SYSTEM] gnome-terminal not found, running sensor in current terminal..."
    run_sensor
fi
