#!/bin/bash

set -euo pipefail

# =========================
# COLORS & UI
# =========================
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
WHITE='\033[1;37m'

# =========================
# LOGGING
# =========================
log_info() { echo -e "${BLUE}[INFO]${RESET} $1"; }
log_success() { echo -e "${GREEN}✓${RESET} $1"; }
log_warning() { echo -e "${YELLOW}⚠${RESET} $1"; }
log_error() { echo -e "${RED}✗${RESET} $1"; }

# =========================
# BANNER
# =========================
print_banner() {
    clear
    echo ""
    echo -e "${CYAN}  ███████╗███████╗██╗███╗   ██╗ █████╗ ${MAGENTA} ZeinaGuard ${RESET}"
    echo -e "${CYAN}  ╚══███╔╝██╔════╝██║████╗  ██║██╔══██╗${RESET}"
    echo -e "${CYAN}    ███╔╝ █████╗  ██║██╔██╗ ██║███████║${RESET}"
    echo -e "${CYAN}   ███╔╝  ██╔══╝  ██║██║╚██╗██║██╔══██║${RESET}"
    echo -e "${CYAN}  ███████╗███████╗██║██║ ╚████║██║  ██║${RESET}"
    echo ""
    echo -e "${DIM}Enterprise Wireless Intrusion Prevention System${RESET}"
    echo ""
}

# =========================
# CLEANUP
# =========================
cleanup() {
    echo ""
    log_warning "Shutting down services..."
    $COMPOSE down --remove-orphans || true
    exit 0
}
trap cleanup INT TERM

# =========================
# DETECT WIFI INTERFACE
# =========================
detect_interface() {
    for iface in $(ls /sys/class/net/); do
        if [ -d /sys/class/net/$iface/wireless ]; then
            echo "$iface"
            return
        fi
    done

    echo "wlan0"
}

# =========================
# DOCKER VALIDATION
# =========================
validate_docker() {
    log_info "Checking Docker..."

    if ! docker info > /dev/null 2>&1; then
        log_error "Docker is not running!"
        exit 1
    fi

    if docker compose version > /dev/null 2>&1; then
        COMPOSE="docker compose"
    else
        COMPOSE="docker-compose"
    fi

    log_success "Docker ready"
}

# =========================
# START SERVICES
# =========================
start_services() {
    log_info "Starting containers..."

    $COMPOSE up -d

    log_success "Containers started"
}

# =========================
# BACKEND HEALTH CHECK
# =========================
wait_for_backend() {
    log_info "Waiting for backend..."

    for i in {1..30}; do
        RESPONSE=$(curl -s http://localhost:5000/health || true)

        if echo "$RESPONSE" | grep -q "healthy"; then
            log_success "Backend is ready"
            return
        fi

        echo -e "${DIM}Attempt $i/30...${RESET}"
        sleep 2
    done

    log_error "Backend failed!"
    $COMPOSE logs flask-backend
    exit 1
}

# =========================
# START SENSOR
# =========================
start_sensor() {
    PROJECT_ROOT=~/FINAL/ZeinaGuard
    SENSOR_PATH="$PROJECT_ROOT/sensor"

    INTERFACE=$(detect_interface)

    log_info "Starting sensor on interface: $INTERFACE"

    run_sensor() {
        cd "$SENSOR_PATH" || exit
        export RUN_MODE=LOCAL
        export ENABLE_TUI=True

        sudo python3 main.py "$INTERFACE"
    }

    if command -v gnome-terminal > /dev/null 2>&1; then
        log_info "Launching sensor in new terminal..."

        gnome-terminal -- bash -c "
        cd '$SENSOR_PATH';
        export RUN_MODE=LOCAL;
        export ENABLE_TUI=True;
        echo '[SENSOR] Running on $INTERFACE';
        sudo python3 main.py $INTERFACE;
        exec bash
        "
    else
        log_warning "No GUI terminal found → running here"
        run_sensor
    fi
}

# =========================
# SUMMARY
# =========================
print_summary() {
    echo ""
    echo -e "${WHITE}========== SYSTEM STATUS ==========${RESET}"
    echo ""
    echo -e "${GREEN}Frontend:${RESET} http://localhost:3000"
    echo -e "${GREEN}Backend:${RESET}  http://localhost:5000"
    echo -e "${GREEN}PgAdmin:${RESET}  http://localhost:5050"
    echo ""
    echo -e "${DIM}Use: docker logs -f <container>${RESET}"
    echo ""
}

# =========================
# MAIN
# =========================
main() {
    print_banner

    validate_docker
    start_services
    wait_for_backend
    start_sensor
    print_summary
}

main "$@"