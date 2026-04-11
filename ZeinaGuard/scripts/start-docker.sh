#!/bin/bash

set -euo pipefail  # Strict mode: exit on error, undefined vars, pipe failures

# ANSI Color Codes for terminal output formatting
readonly RESET='\033[0m'           # Reset all formatting
readonly BOLD='\033[1m'            # Bold text
readonly DIM='\033[2m'             # Dimmed text

# Status Colors
readonly GREEN='\033[0;32m'        # Success / Healthy
readonly RED='\033[0;31m'          # Error / Critical
readonly YELLOW='\033[1;33m'       # Warning / Caution
readonly BLUE='\033[0;34m'         # Info / Processing
readonly CYAN='\033[0;36m'         # Accent / Highlight
readonly MAGENTA='\033[0;35m'      # Special / Admin
readonly WHITE='\033[1;37m'        # Bright text
readonly UNDERLINE='\033[4m'

# Background Colors for critical alerts
readonly BG_RED='\033[41m'
readonly BG_GREEN='\033[42m'

# Service credentials - can be overridden via environment variables
readonly REDIS_PASSWORD="${REDIS_PASSWORD:-redis_password_change_me}"
readonly DB_USER="${DB_USER:-zeinaguard_user}"
readonly DB_NAME="${DB_NAME:-zeinaguard_db}"
readonly DB_PASSWORD="${DB_PASSWORD:-secure_password_change_me}"

# ==============================================================================
# TYPOGRAPHY - Creative ASCII Art Banner
# ==============================================================================

# Function: print_banner
# Displays stylized ZeinaGuard logo using ASCII art with gradient effect
print_banner() {
    clear  # Clear terminal for clean presentation
    
    echo ""
    echo -e "${CYAN}  █████████╗███████╗██╗███╗   ██╗ █████╗ ${MAGENTA}  ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ ${RESET}"
    echo -e "${CYAN}  ╚════███╔╝██╔════╝██║████╗  ██║██╔══██╗${MAGENTA} ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗${RESET}"
    echo -e "${CYAN}     ███╔╝  █████╗  ██║██╔██╗ ██║███████║${MAGENTA} ██║  ███╗██║   ██║███████║██████╔╝██║  ██║${RESET}"
    echo -e "${CYAN}   ███╔╝    ██╔══╝  ██║██║╚██╗██║██╔══██║${MAGENTA} ██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║${RESET}"
    echo -e "${CYAN}  █████████╗███████╗██║██║ ╚████║██║  ██║${MAGENTA} ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝${RESET}"
    echo -e "${CYAN}  ╚════════╝╚══════╝╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝${MAGENTA}  ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ${RESET}"
    echo ""
    echo -e "${DIM}                    Enterprise Wireless Intrusion Prevention System${RESET}"
    echo -e "${DIM}                              Version 1.0.0 | Build 2026${RESET}"
    echo ""
    echo -e "${WHITE}═══════════════════════════════════════════════════════════════════════════════════════════════${RESET}"
    echo ""
}

# ==============================================================================
# CONFIGURATION - Service Parameters
# ==============================================================================

# Maximum wait attempts for health checks (30 attempts × 2 seconds = 60 seconds max)
readonly MAX_RETRIES=30

# Sleep interval between health check attempts (seconds)
readonly RETRY_INTERVAL=2

# Service endpoint configurations
readonly FLASK_HEALTH_URL="http://localhost:5000/health"
readonly FRONTEND_URL="http://localhost:3000"

# ==============================================================================
# UTILITY FUNCTIONS - Helper Methods
# ==============================================================================

# Function: log_info
# Prints informational messages in blue
# Arguments: $1 = message string
log_info() {
    echo -e "${BLUE}[INFO]${RESET} $1"
}

# Function: log_success
# Prints success messages with green checkmark
# Arguments: $1 = message string
log_success() {
    echo -e "${GREEN}✓${RESET} $1"
}

# Function: log_warning
# Prints warning messages with yellow indicator
# Arguments: $1 = message string
log_warning() {
    echo -e "${YELLOW}⚠${RESET} $1"
}

# Function: log_error
# Prints error messages with red X marker
# Arguments: $1 = message string
log_error() {
    echo -e "${RED}✗${RESET} $1"
}

# Function: log_step
# Prints step headers with cyan color and numbering
# Arguments: $1 = step number, $2 = description
log_step() {
    echo ""
    echo -e "${CYAN}${BOLD}Step $1:${RESET} ${WHITE}$2${RESET}"
    echo -e "${DIM}────────────────────────────────────────────────────────────────${RESET}"
}

# ==============================================================================
# CLEANUP HANDLER - Graceful Shutdown
# ==============================================================================

# Function: cleanup
# Executes on script interruption (SIGINT/SIGTERM)
# Stops all Docker services to prevent resource leaks
cleanup() {
    echo ""
    echo ""
    log_warning "Interrupt signal received. Initiating graceful shutdown..."
    
    local compose_cmd="${COMPOSE:-}"
    if [[ -z "$compose_cmd" ]]; then
        if docker compose version > /dev/null 2>&1; then
            compose_cmd="docker compose"
        elif docker-compose version > /dev/null 2>&1; then
            compose_cmd="docker-compose"
        fi
    fi
    
    if [[ -n "$compose_cmd" ]]; then
        echo -e "${DIM}Stopping all services...${RESET}"
        $compose_cmd down --remove-orphans 2>/dev/null || true
    fi
    
    echo -e "${GREEN}Cleanup completed.${RESET}"
    exit 130
}

# Register cleanup function for interrupt signals
trap cleanup INT TERM

# ==============================================================================
# VALIDATION - Pre-flight Checks with Auto-Installation
# ==============================================================================

# Function: validate_docker
# Verifies Docker daemon is running and accessible
# Enhanced to handle missing Docker Compose with auto-installation option
validate_docker() {
    log_step "1" "Environment Validation"
    
    # Check 1: Docker daemon status
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker daemon is not running"
        echo ""
        echo -e "${YELLOW}Troubleshooting:${RESET}"
        echo "  • Start Docker Desktop (Windows/Mac)"
        echo "  • Run: sudo systemctl enable docker && sudo systemctl start docker (Linux)"
        echo "  • Check Docker installation: docker --version"
        echo ""
        exit 1
    fi
    
    log_success "Docker daemon is running"
    
    # Check 2: Docker Compose availability with fallback strategies
    if docker compose version > /dev/null 2>&1; then
        # Docker Compose V2 (plugin) - preferred modern approach
        COMPOSE="docker compose"
        log_success "Docker Compose V2 detected (modern plugin)"
        
    elif docker-compose version > /dev/null 2>&1; then
        # Docker Compose V1 (standalone) - legacy but functional
        COMPOSE="docker-compose"
        log_warning "Docker Compose V1 detected (legacy standalone)"
        echo -e "${DIM}  Consider upgrading: https://docs.docker.com/compose/install/${RESET}"
        
    else
        # Neither version found - attempt recovery
        log_error "Docker Compose not found"
        echo ""
        echo -e "${YELLOW}Docker Compose is required but not installed.${RESET}"
        echo ""
        
        # Detect operating system for platform-specific guidance
        local os_type
        os_type=$(uname -s)
        
        echo -e "${CYAN}Installation options:${RESET}"
        echo ""
        
        case "$os_type" in
            Linux*)
                echo -e "${WHITE}Linux detected. Choose installation method:${RESET}"
                echo ""
                echo "  ${GREEN}[1]${RESET} Install via package manager (recommended)"
                echo "      Ubuntu/Debian:  sudo apt-get install docker-compose-plugin"
                echo "      RHEL/CentOS:    sudo yum install docker-compose-plugin"
                echo "      Arch:           sudo pacman -S docker-compose"
                echo ""
                echo "  ${GREEN}[2]${RESET} Manual installation (latest version)"
                echo "      curl -SL https://github.com/docker/compose/releases/download/v2.23.0/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose"
                echo "      chmod +x ~/.docker/cli-plugins/docker-compose"
                echo ""
                ;;
                
            Darwin*)
                echo -e "${WHITE}macOS detected:${RESET}"
                echo "  Option A: brew install docker-compose"
                echo "  Option B: Download Docker Desktop (includes Compose)"
                echo ""
                ;;
                
            MINGW*|CYGWIN*|MSYS*)
                echo -e "${WHITE}Windows detected:${RESET}"
                echo "  Option A: choco install docker-compose"
                echo "  Option B: Download Docker Desktop (includes Compose)"
                echo ""
                ;;
        esac
        
        # Offer automatic installation attempt
        echo -e "${CYAN}Or let this script attempt installation?${RESET}"
        echo ""
        read -p "  Attempt auto-install? [y/N]: " response
        
        if [[ "$response" =~ ^[Yy]$ ]]; then
            echo ""
            log_info "Attempting Docker Compose installation..."
            
            if attempt_compose_install; then
                # Re-verify after installation
                if docker compose version > /dev/null 2>&1; then
                    COMPOSE="docker compose"
                    log_success "Docker Compose installed successfully!"
                elif docker-compose version > /dev/null 2>&1; then
                    COMPOSE="docker-compose"
                    log_success "Docker Compose installed successfully!"
                else
                    log_error "Installation appeared to succeed but compose not found"
                    exit 1
                fi
            else
                log_error "Automatic installation failed"
                echo "  Please install manually and re-run this script"
                exit 1
            fi
        else
            echo ""
            log_info "Please install Docker Compose and re-run"
            exit 1
        fi
    fi
    
    # Final validation: Verify compose command works
    if ! $COMPOSE version > /dev/null 2>&1; then
        log_error "Docker Compose command failed validation"
        exit 1
    fi
    
    log_info "Working directory: $(pwd)"
    log_info "Docker Compose command: ${CYAN}$COMPOSE${RESET}"
}

# Function: attempt_compose_install
# Platform-specific auto-installation logic
attempt_compose_install() {
    local os_type=$(uname -s)
    
    case "$os_type" in
        Linux*)
            # Try package manager first
            if command -v apt-get > /dev/null 2>&1; then
                log_info "Attempting apt-get installation..."
                sudo apt-get update -qq
                sudo apt-get install -y docker-compose-plugin 2>/dev/null && return 0
                # Fallback to docker-compose package
                sudo apt-get install -y docker-compose 2>/dev/null && return 0
                
            elif command -v yum > /dev/null 2>&1; then
                log_info "Attempting yum installation..."
                sudo yum install -y docker-compose-plugin 2>/dev/null && return 0
                
            elif command -v pacman > /dev/null 2>&1; then
                log_info "Attempting pacman installation..."
                sudo pacman -S --noconfirm docker-compose 2>/dev/null && return 0
            fi
            
            # Manual installation as last resort
            log_info "Attempting manual installation..."
            mkdir -p ~/.docker/cli-plugins/
            curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
                -o ~/.docker/cli-plugins/docker-compose 2>/dev/null
            chmod +x ~/.docker/cli-plugins/docker-compose 2>/dev/null
            return 0
            ;;
            
        Darwin*)
            if command -v brew > /dev/null 2>&1; then
                log_info "Attempting brew installation..."
                brew install docker-compose 2>/dev/null && return 0
            fi
            return 1
            ;;
            
        *)
            log_warning "Auto-install not supported on this platform"
            return 1
            ;;
    esac
}

# ==============================================================================
# SERVICE ORCHESTRATION - Container Management
# ==============================================================================

# Function: start_services
# Initializes all containerized services in detached mode
start_services() {
    log_step "2" "Service Orchestration"
    
    log_info "Building and starting containers..."
    
    # Pull latest images (optional)
    log_info "Pulling latest images..."
    if ! $COMPOSE pull 2>/dev/null; then
        log_warning "Some images could not be pulled (will build locally)"
    fi
    
    # Build and start with proper error detection
    echo ""
    if ! $COMPOSE up -d --build --remove-orphans 2>&1; then
        log_error "Docker Compose failed to start services!"
        echo ""
        echo -e "${YELLOW}Diagnostic commands:${RESET}"
        echo "  $COMPOSE ps -a          # Check container status"
        echo "  $COMPOSE logs           # View service logs"
        exit 1
    fi
    
    # Verify containers actually started
    local running_count=0
    local wait_count=0
    while [[ "$running_count" -eq 0 && "$wait_count" -lt 10 ]]; do
        sleep 1
        ((wait_count++))
        running_count=$($COMPOSE ps -q 2>/dev/null | wc -l)
    done
    
    # Check if still no containers after waiting
    if [[ "$running_count" -eq 0 ]]; then
        log_error "No containers started after waiting!"
        echo ""
        echo -e "${YELLOW}Check for errors:${RESET}"
        echo "  $COMPOSE ps -a          # See all containers (including exited)"
        echo "  $COMPOSE logs           # View service logs"
        exit 1
    fi
    
    log_success "Containers started ($running_count services)"
    
    # Show actual status
    echo ""
    $COMPOSE ps
    echo ""
}

# ==============================================================================
# HEALTH CHECK SYSTEM - Service Verification
# ==============================================================================

# Function: check_postgresql
# Validates PostgreSQL + TimescaleDB availability with database connectivity test
check_postgresql() {
    log_step "3" "Database Health Verification"
    
    local retries=0
    local postgres_ready=false
    local db_accessible=false
    local timescaledb_ready=false
    
    log_info "Checking PostgreSQL availability..."
    
    while [[ $retries -lt $MAX_RETRIES ]]; do
        ((retries++))
        
        # Check 1: PostgreSQL server accepting connections
        if $COMPOSE exec -T postgres pg_isready \
            -U zeinaguard_user \
            -d zeinaguard_db > /dev/null 2>&1; then
            
            if [[ "$postgres_ready" == false ]]; then
                log_success "PostgreSQL server accepting connections"
                postgres_ready=true
            fi
            
            # Check 2: Actual database query execution (verifies schema initialization)
            if $COMPOSE exec -T postgres psql \
                -U zeinaguard_user \
                -d zeinaguard_db \
                -c "SELECT version(), current_database(), NOW();" > /dev/null 2>&1; then
                
                # Check 3: TimescaleDB extension loaded
                if [[ "$timescaledb_ready" == false ]]; then
                    if $COMPOSE exec -T postgres psql \
                        -U zeinaguard_user \
                        -d zeinaguard_db \
                        -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';" 2>/dev/null | grep -q "timescaledb"; then
                        log_success "TimescaleDB extension is loaded"
                        timescaledb_ready=true
                    fi
                fi
                
                log_success "Database 'zeinaguard_db' accessible and queryable"
                db_accessible=true
                break
            fi
        fi
        
        echo -e "${DIM}  Attempt $retries/$MAX_RETRIES (waiting for initialization)...${RESET}"
        sleep $RETRY_INTERVAL
    done
    
    if [[ "$db_accessible" == false ]]; then
        echo ""
        log_error "PostgreSQL failed to initialize within ${MAX_RETRIES} attempts"
        echo ""
        echo -e "${YELLOW}Diagnostic commands:${RESET}"
        echo "  $COMPOSE logs postgres    # View database logs"
        echo "  $COMPOSE ps               # Check container status"
        echo ""
        exit 1
    fi
    
    # Warning if TimescaleDB not detected (non-critical)
    if [[ "$timescaledb_ready" == false ]]; then
        log_warning "TimescaleDB extension not detected (non-critical for basic operation)"
    fi
}

# Function: check_redis
# Validates Redis cache/queue service with authentication
check_redis() {
    log_info "Checking Redis availability..."
    
    local retries=0
    
    while [[ $retries -lt $MAX_RETRIES ]]; do
        ((retries++))
        
        # Authenticated ping test (matches docker-compose password)
        local response
        response=$($COMPOSE exec -T redis redis-cli \
            -a redis_password_change_me \
            ping 2>/dev/null) || true
        
        if [[ "$response" == "PONG" ]]; then
            log_success "Redis responding to authenticated commands"
            return 0
        fi
        
        sleep $RETRY_INTERVAL
    done
    
    log_warning "Redis health check inconclusive (non-critical, continuing)"
    return 0  # Redis is not critical for basic operation
}

# Function: check_flask_api
# Validates Flask backend API health endpoint with retry logic
check_flask_api() {
    log_step "4" "API Layer Verification"
    
    log_info "Checking Flask REST API..."
    
    local retries=0
    local flask_ready=false
    
    while [[ $retries -lt $MAX_RETRIES ]]; do
        ((retries++))
        
        # Check if container died during startup (before curl to catch early exits)
        local container_line
        container_line=$($COMPOSE ps 2>/dev/null | grep "^zeinaguard_flask-backend" || true)
        
        if [[ -n "$container_line" ]] && echo "$container_line" | grep -q "Exit"; then
            log_error "Flask container has stopped unexpectedly!"
            echo ""
            echo -e "${YELLOW}Last 20 log lines:${RESET}"
            $COMPOSE logs --tail=20 flask-backend 2>/dev/null
            exit 1
        fi
        
        # HTTP health check with curl (silent, follow redirects, fail on error)
        if curl -sfS \
            --max-time 5 \
            --retry 0 \
            "$FLASK_HEALTH_URL" > /dev/null 2>&1; then
            
            log_success "Flask API responding on port 5000"
            flask_ready=true
            break
        fi
        
        echo -e "${DIM}  Attempt $retries/$MAX_RETRIES (API initializing)...${RESET}"
        sleep $RETRY_INTERVAL
    done
    
    if [[ "$flask_ready" == false ]]; then
        log_warning "Flask API not responding (may still be initializing)"
        echo -e "${DIM}  Check status manually: curl $FLASK_HEALTH_URL${RESET}"
    fi
}

# Function: check_frontend
check_frontend() {
    log_info "Checking Next.js frontend..."
    
    local retries=0
    while [[ $retries -lt 10 ]]; do
        ((retries++))
        if curl -sfS --max-time 3 "$FRONTEND_URL" > /dev/null 2>&1; then
            log_success "Frontend responding on port 3000"
            return 0
        fi
        sleep 3
    done
    
    log_warning "Frontend not responding after 30 seconds (check: $COMPOSE logs next-frontend)"
}

# ==============================================================================
# SUMMARY REPORT - Status Dashboard
# ==============================================================================

# Function: print_summary
print_summary() {
    echo ""
    echo -e "${WHITE}╔══════════════════════════════════════════════════════════════════════════════╗${RESET}"
    echo -e "${WHITE}║${RESET}          ${GREEN}${BOLD}ZEINAGUARD${RESET} - ${CYAN}System Status${RESET}                                  ${WHITE}║${RESET}"
    echo -e "${WHITE}╚══════════════════════════════════════════════════════════════════════════════╝${RESET}"
    echo ""
    
    echo -e "${BOLD}Service Status Overview:${RESET}"
    echo ""
    printf "  ${WHITE}%-20s %-15s %-25s${RESET}\n" "SERVICE" "STATUS" "ENDPOINT"
    echo -e "  ${DIM}────────────────────────────────────────────────────────────${RESET}"
    
    # Service names from docker-compose.yml (exact match!)
    local services=("postgres" "redis" "flask-backend" "next-frontend" "pgadmin" "sensor")
    local ports=("5432" "6379" "5000" "3000" "5050" "N/A")
    local names=("PostgreSQL" "Redis" "Flask API" "Next.js UI" "PgAdmin" "WIPS Sensor")
    
    for i in "${!services[@]}"; do
        local service="${services[$i]}"
        local port="${ports[$i]}"
        local name="${names[$i]}"
        local status_text="● Missing"
        local status_color="${RED}"
        
        # Container name: zeinaguard_ + service name (with hyphens preserved)
        local container_name="zeinaguard_${service}"
        local container_line
        container_line=$($COMPOSE ps 2>/dev/null | grep "^${container_name}" || true)
        
        if [[ -n "$container_line" ]]; then
            if echo "$container_line" | grep -q "healthy"; then
                status_color="${GREEN}"
                status_text="● Healthy"
            elif echo "$container_line" | grep -q "Up"; then
                status_color="${YELLOW}"
                status_text="○ Running"
            elif echo "$container_line" | grep -q "unhealthy"; then
                status_color="${RED}"
                status_text="● Unhealthy"
            elif echo "$container_line" | grep -q "Exit"; then
                status_color="${RED}"
                status_text="● Stopped"
            fi
        fi
        
        # Special handling for PostgreSQL: add TimescaleDB indicator if loaded
        if [[ "$service" == "postgres" ]]; then
            local tsdb_status=""
            if $COMPOSE exec -T postgres psql -U zeinaguard_user -d zeinaguard_db -c "SELECT 1 FROM pg_extension WHERE extname='timescaledb';" 2>/dev/null | grep -q "1 row"; then
                tsdb_status=" (+TSDB)"
            fi
            printf "  ${CYAN}%-20s${RESET} ${status_color}%-15s${RESET} ${MAGENTA}%-25s${RESET}\n" \
                "PostgreSQL${tsdb_status}" "$status_text" "localhost:$port"
        else
            printf "  ${CYAN}%-20s${RESET} ${status_color}%-15s${RESET} ${MAGENTA}%-25s${RESET}\n" \
                "$name" "$status_text" "localhost:$port"
        fi
        
        # Hint for missing next-frontend
        if [[ "$status_text" == "● Missing" && "$service" == "next-frontend" ]]; then
            echo -e "${DIM}    Hint: Check build errors with: $COMPOSE logs next-frontend${RESET}"
        fi
    done
    
    echo ""
    echo -e "${BOLD}Application Access URLs:${RESET}"
    echo ""
    echo -e "  ${GREEN}🌐 Dashboard (UI)${RESET}      ${WHITE}→${RESET} ${UNDERLINE}http://localhost:3000${RESET}"
    echo -e "  ${BLUE}⚙️  API & WebSocket${RESET}    ${WHITE}→${RESET} ${UNDERLINE}http://localhost:5000${RESET}"
    echo -e "  ${MAGENTA}🗄️  Database Admin${RESET}    ${WHITE}→${RESET} ${UNDERLINE}http://localhost:5050${RESET}"
    echo ""
    echo -e "${BOLD}Management Commands:${RESET}"
    echo ""
    printf "  ${YELLOW}%-35s${RESET} %s\n" "Interact with WIPS Sensor UI:" "docker attach zeinaguard_sensor"
    printf "  ${YELLOW}%-35s${RESET} %s\n" "View all logs:" "$COMPOSE logs -f"
    printf "  ${YELLOW}%-35s${RESET} %s\n" "Stop all services:" "$COMPOSE down"
    printf "  ${YELLOW}%-35s${RESET} %s\n" "Restart service:" "$COMPOSE restart <service>"
    printf "  ${YELLOW}%-35s${RESET} %s\n" "Check status:" "$COMPOSE ps"
    echo ""
    echo -e "${DIM}══════════════════════════════════════════════════════════════════════════════${RESET}"
    echo -e "${DIM}  ZeinaGuard v1.0.0 | Enterprise WIPS | © 2026${RESET}"
    echo -e "${DIM}══════════════════════════════════════════════════════════════════════════════${RESET}"
    echo ""
}

# ==============================================================================
# MAIN EXECUTION - Script Entry Point
# ==============================================================================

main() {
    # Change to project root (script is in scripts/, go up one level)
    cd "$(dirname "$0")/.."
    
    # Display creative banner
    print_banner
    
    # Phase 1: Environment validation
    validate_docker
    
    # Phase 2: Service initialization
    start_services
    
    # Phase 3: Health verification (database layer)
    check_postgresql
    check_redis
    
    # Phase 4: API layer verification
    check_flask_api
    check_frontend
    
    # Phase 5: Display summary
    print_summary
    
    # Successful exit
    exit 0
}

# Execute main function with all script arguments
main "$@"
