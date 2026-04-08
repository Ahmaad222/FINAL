#!/bin/bash

# ==============================================================================
# ZeinaGuard - Production Startup Script
# ==============================================================================
# This script orchestrates the deployment of the ZeinaGuard Enterprise WIPS.
# It handles environment validation, service building, health checks,
# and provides a comprehensive status dashboard.
# ==============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# --- Terminal Formatting (ANSI) ---
readonly RESET='\033[0m'
readonly BOLD='\033[1m'
readonly DIM='\033[2m'
readonly GREEN='\033[0;32m'
readonly RED='\033[0;31m'
readonly YELLOW='\033[1;33m'
readonly BLUE='\033[0;34m'
readonly CYAN='\033[0;36m'
readonly MAGENTA='\033[0;35m'
readonly WHITE='\033[1;37m'
readonly UNDERLINE='\033[4m'

# --- Configuration Constants ---
readonly MAX_RETRIES=30
readonly RETRY_INTERVAL=2
readonly PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
readonly ENV_FILE="${PROJECT_ROOT}/.env"
readonly ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"

# Service endpoints for health checks
readonly FLASK_HEALTH_URL="http://localhost:5000/health"
readonly FRONTEND_URL="http://localhost:3000"

# Global Compose Command (populated by validate_docker)
COMPOSE=""

# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================

log_info()    { echo -e "${BLUE}[INFO]${RESET} $1"; }
log_success() { echo -e "${GREEN}✓${RESET} $1"; }
log_warning() { echo -e "${YELLOW}⚠${RESET} $1"; }
log_error()   { echo -e "${RED}✗${RESET} $1"; }
log_step()    { 
    echo -e "\n${CYAN}${BOLD}Step $1:${RESET} ${WHITE}$2${RESET}"
    echo -e "${DIM}────────────────────────────────────────────────────────────────${RESET}"
}

print_banner() {
    clear
    echo -e "${CYAN}  █████████╗███████╗██╗███╗   ██╗ █████╗ ${MAGENTA}  ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ ${RESET}"
    echo -e "${CYAN}  ╚════███╔╝██╔════╝██║████╗  ██║██╔══██╗${MAGENTA} ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗${RESET}"
    echo -e "${CYAN}     ███╔╝  █████╗  ██║██╔██╗ ██║███████║${MAGENTA} ██║  ███╗██║   ██║███████║██████╔╝██║  ██║${RESET}"
    echo -e "${CYAN}   ███╔╝    ██╔══╝  ██║██║╚██╗██║██╔══██║${MAGENTA} ██║   ██║██║   ██║███████║██╔══██╗██║  ██║${RESET}"
    echo -e "${CYAN}  █████████╗███████╗██║██║ ╚████║██║  ██║${MAGENTA} ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝${RESET}"
    echo -e "${CYAN}  ╚════════╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝${MAGENTA}  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ${RESET}"
    echo -e "\n${DIM}                    Enterprise Wireless Intrusion Prevention System${RESET}"
    echo -e "${DIM}                              Production Deployment Manager${RESET}\n"
}

cleanup() {
    echo ""
    log_warning "Interrupt signal received. Initiating graceful shutdown..."
    if [[ -n "$COMPOSE" ]]; then
        $COMPOSE down --remove-orphans 2>/dev/null || true
    fi
    log_success "Cleanup completed."
    exit 0
}

trap cleanup INT TERM

# ==============================================================================
# VALIDATION & SETUP
# ==============================================================================

setup_environment() {
    log_step "1" "Environment Configuration"
    
    if [[ ! -f "$ENV_FILE" ]]; then
        log_warning ".env file not found. Creating from template..."
        if [[ -f "$ENV_EXAMPLE" ]]; then
            cp "$ENV_EXAMPLE" "$ENV_FILE"
            # Generate a random JWT secret key for security
            if command -v openssl > /dev/null; then
                local secret=$(openssl rand -hex 32)
                sed -i "s/your_jwt_secret_key_change_me/$secret/g" "$ENV_FILE"
            fi
            log_success ".env file created. Please review credentials before production use."
        else
            log_error ".env.example not found. Cannot initialize environment."
            exit 1
        fi
    else
        log_success "Environment file (.env) detected."
    fi

    # Load environment variables for the health check functions
    source "$ENV_FILE"
}

validate_docker() {
    log_step "2" "Docker Infrastructure Check"
    
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker daemon is not running."
        exit 1
    fi
    log_success "Docker daemon is healthy."

    if docker compose version > /dev/null 2>&1; then
        COMPOSE="docker compose"
    elif docker-compose version > /dev/null 2>&1; then
        COMPOSE="docker-compose"
    else
        log_error "Docker Compose (v2 or v1) is not installed."
        exit 1
    fi
    log_success "Using $( $COMPOSE version | head -n 1 )"
}

# ==============================================================================
# SERVICE OPERATIONS
# ==============================================================================

start_services() {
    local clean_start=${1:-false}
    
    log_step "3" "Service Orchestration"
    
    if [[ "$clean_start" == true ]]; then
        log_warning "Performing a clean start (removing old volumes)..."
        $COMPOSE down -v --remove-orphans
    fi

    log_info "Building and starting ZeinaGuard containers..."
    
    # Increase Docker BuildKit timeout/robustness for slow networks
    export DOCKER_BUILDKIT=1
    export COMPOSE_DOCKER_CLI_BUILD=1

    if ! $COMPOSE up -d --build --remove-orphans; then
        log_error "Deployment failed. Check 'docker compose logs' for details."
        exit 1
    fi
    log_success "All services are up in detached mode."
}

check_health() {
    log_step "4" "Multi-Layer Health Verification"

    # --- Database Layer ---
    log_info "Verifying Database Layer (PostgreSQL + TimescaleDB)..."
    local retries=0
    while [[ $retries -lt $MAX_RETRIES ]]; do
        if $COMPOSE exec -T postgres pg_isready -U "${DB_USER:-zeinaguard_user}" -d "${DB_NAME:-zeinaguard_db}" > /dev/null 2>&1; then
            log_success "PostgreSQL is ready."
            break
        fi
        ((retries++))
        echo -n "."
        sleep $RETRY_INTERVAL
    done
    [[ $retries -eq $MAX_RETRIES ]] && { log_error "Database timeout."; exit 1; }

    # --- API Layer ---
    log_info "Verifying API Layer (Flask + Gunicorn)..."
    retries=0
    while [[ $retries -lt $MAX_RETRIES ]]; do
        if curl -sfS "$FLASK_HEALTH_URL" > /dev/null 2>&1; then
            log_success "Flask API is healthy."
            break
        fi
        ((retries++))
        echo -n "."
        sleep $RETRY_INTERVAL
    done
    [[ $retries -eq $MAX_RETRIES ]] && log_warning "API health check inconclusive (may still be booting)."

    # --- Frontend Layer ---
    log_info "Verifying Frontend Layer (Next.js)..."
    if curl -sfS --max-time 5 "$FRONTEND_URL" > /dev/null 2>&1; then
        log_success "Frontend Dashboard is live."
    else
        log_warning "Frontend check timed out (check: $COMPOSE logs next-frontend)."
    fi
}

print_summary() {
    echo -e "\n${BOLD}${WHITE}╔══════════════════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${WHITE}║${RESET}          ${GREEN}${BOLD}ZEINAGUARD${RESET} - ${CYAN}Production System Status${RESET}                          ${WHITE}║${RESET}"
    echo -e "${WHITE}╚══════════════════════════════════════════════════════════════════════════════╝${RESET}\n"
    
    $COMPOSE ps
    
    echo -e "\n${BOLD}Access Endpoints:${RESET}"
    echo -e "  ${GREEN}🌐 Dashboard:${RESET}  ${UNDERLINE}http://localhost:3000${RESET}"
    echo -e "  ${BLUE}⚙️  Backend API:${RESET} ${UNDERLINE}http://localhost:5000${RESET}"
    echo -e "  ${MAGENTA}🗄️  DB Admin:${RESET}   ${UNDERLINE}http://localhost:5050${RESET}\n"
    
    log_info "To view live logs, run: ${YELLOW}$COMPOSE logs -f${RESET}"
    echo -e "${DIM}ZeinaGuard v1.0.0 | Enterprise WIPS System${RESET}\n"
}

# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

main() {
    local clean=false
    if [[ "${1:-}" == "--clean" ]]; then
        clean=true
    fi

    cd "$PROJECT_ROOT"
    print_banner
    
    setup_environment
    validate_docker
    start_services "$clean"
    check_health
    print_summary
}

main "$@"
