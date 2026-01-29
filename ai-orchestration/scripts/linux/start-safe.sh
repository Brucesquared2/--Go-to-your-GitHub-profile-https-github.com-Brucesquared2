#!/bin/bash
#
# AI Stack - SAFE Startup Script
#
# This script starts the AI stack using the SAFE service daemon architecture:
# - UNIX sockets for IPC (fast, crash-isolated)
# - Watchdog for automatic recovery
# - Graceful degradation when backends fail
# - Kernel module is OPTIONAL and disabled by default
#
# Unlike kernel modules, if the service crashes, your system stays stable.
#
# Usage:
#   ./start-safe.sh              # Start with safe defaults
#   ./start-safe.sh --enable-kernel  # Enable kernel module (not recommended)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Defaults - SAFE configuration
ENABLE_KERNEL=false
DEBUG=false
FOREGROUND=false

# Runtime directories
SOCKET_DIR="/var/run/ai-service"
LOG_DIR="/var/log/ai-service"
SOCKET_PATH="${SOCKET_DIR}/ai.sock"

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_safe() { echo -e "${CYAN}[SAFE]${NC} $1"; }

show_banner() {
    echo ""
    echo -e "${CYAN}╔═══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║     AI Orchestration Stack - SAFE MODE                    ║${NC}"
    echo -e "${CYAN}║                                                           ║${NC}"
    echo -e "${CYAN}║  Using UNIX sockets (not kernel modules) for stability    ║${NC}"
    echo -e "${CYAN}╚═══════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

check_dependencies() {
    log_info "Checking dependencies..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is required"
        exit 1
    fi

    # Check for requests library
    if ! python3 -c "import requests" 2>/dev/null; then
        log_warn "Installing Python requests library..."
        pip3 install requests --quiet
    fi

    log_info "Dependencies OK"
}

setup_directories() {
    log_info "Setting up runtime directories..."

    # Create directories (may need sudo)
    for dir in "$SOCKET_DIR" "$LOG_DIR"; do
        if [[ ! -d "$dir" ]]; then
            if [[ $EUID -eq 0 ]]; then
                mkdir -p "$dir"
                chmod 755 "$dir"
            else
                sudo mkdir -p "$dir"
                sudo chmod 755 "$dir"
                sudo chown $USER:$USER "$dir"
            fi
        fi
    done
}

start_ollama() {
    log_info "Checking Ollama..."

    # Check if running
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        log_info "Ollama already running"
        return 0
    fi

    # Check if installed
    if ! command -v ollama &>/dev/null; then
        log_error "Ollama not installed. Get it from: https://ollama.ai"
        return 1
    fi

    log_info "Starting Ollama..."
    nohup ollama serve > "${LOG_DIR}/ollama.log" 2>&1 &
    local pid=$!
    echo "$pid" > "${SOCKET_DIR}/ollama.pid"

    # Wait for ready
    local count=0
    while ! curl -s http://localhost:11434/api/tags &>/dev/null; do
        sleep 1
        count=$((count + 1))
        if [[ $count -ge 30 ]]; then
            log_error "Ollama failed to start"
            return 1
        fi
        echo -n "."
    done
    echo ""

    log_info "Ollama started (PID: $pid)"
    return 0
}

ensure_model() {
    local model="${1:-llama2}"
    log_info "Ensuring model: $model"

    if ollama list 2>/dev/null | grep -q "^$model"; then
        log_info "Model $model available"
        return 0
    fi

    log_info "Pulling model $model (this may take a while)..."
    ollama pull "$model"
}

start_service_daemon() {
    log_info "Starting AI Service Daemon (SAFE mode)..."
    log_safe "Using UNIX socket: $SOCKET_PATH"
    log_safe "Kernel module: DISABLED (for stability)"

    local daemon_script="${PROJECT_ROOT}/services/ai_service_daemon.py"

    if [[ ! -f "$daemon_script" ]]; then
        log_error "Service daemon not found: $daemon_script"
        return 1
    fi

    local args="--socket $SOCKET_PATH"
    [[ "$DEBUG" == "true" ]] && args="$args --debug"
    [[ "$ENABLE_KERNEL" == "true" ]] && args="$args --enable-kernel"

    if [[ "$FOREGROUND" == "true" ]]; then
        python3 "$daemon_script" $args start
    else
        nohup python3 "$daemon_script" $args start > "${LOG_DIR}/ai-service.log" 2>&1 &
        local pid=$!
        sleep 2

        if kill -0 "$pid" 2>/dev/null; then
            log_info "Service daemon started (PID: $pid)"
        else
            log_error "Service daemon failed. Check: ${LOG_DIR}/ai-service.log"
            return 1
        fi
    fi
}

show_status() {
    echo ""
    echo "═══════════════════════════════════════════════════════════"
    echo "  AI Stack Status (SAFE MODE)"
    echo "═══════════════════════════════════════════════════════════"
    echo ""

    # Ollama
    echo -n "  Ollama:          "
    if curl -s http://localhost:11434/api/tags &>/dev/null; then
        echo -e "${GREEN}RUNNING${NC}"
    else
        echo -e "${RED}STOPPED${NC}"
    fi

    # Socket
    echo -n "  Socket:          "
    if [[ -S "$SOCKET_PATH" ]]; then
        echo -e "${GREEN}$SOCKET_PATH${NC}"
    else
        echo -e "${YELLOW}Not created${NC}"
    fi

    # Service daemon
    echo -n "  Service Daemon:  "
    if [[ -f "${SOCKET_DIR}/ai.pid" ]]; then
        local pid=$(cat "${SOCKET_DIR}/ai.pid")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "${GREEN}RUNNING${NC} (PID: $pid)"
        else
            echo -e "${RED}STOPPED${NC}"
        fi
    else
        echo -e "${YELLOW}NOT STARTED${NC}"
    fi

    # Kernel module (should be disabled)
    echo -n "  Kernel Module:   "
    if lsmod 2>/dev/null | grep -q "^claude_module"; then
        echo -e "${YELLOW}LOADED (not recommended)${NC}"
    else
        echo -e "${GREEN}DISABLED (safe)${NC}"
    fi

    echo ""
    echo "  Connect: python3 -c \"from ai_client import AIClient; print(AIClient().prompt('Hello'))\""
    echo ""
}

stop_all() {
    log_info "Stopping AI Stack..."

    # Stop service daemon
    if [[ -f "${SOCKET_DIR}/ai.pid" ]]; then
        local pid=$(cat "${SOCKET_DIR}/ai.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            log_info "Stopped service daemon"
        fi
        rm -f "${SOCKET_DIR}/ai.pid"
    fi

    # Stop Ollama (optional)
    if [[ -f "${SOCKET_DIR}/ollama.pid" ]]; then
        local pid=$(cat "${SOCKET_DIR}/ollama.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid"
            log_info "Stopped Ollama"
        fi
        rm -f "${SOCKET_DIR}/ollama.pid"
    fi

    # Clean up socket
    rm -f "$SOCKET_PATH"

    log_info "Stack stopped"
}

show_help() {
    echo "AI Orchestration Stack - SAFE Startup"
    echo ""
    echo "Usage: $0 [OPTIONS] [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start       Start all services (default)"
    echo "  stop        Stop all services"
    echo "  restart     Restart all services"
    echo "  status      Show status"
    echo ""
    echo "Options:"
    echo "  --enable-kernel   Enable kernel module (NOT recommended)"
    echo "  --foreground      Run in foreground"
    echo "  --debug           Enable debug logging"
    echo "  -h, --help        Show this help"
    echo ""
    echo "SAFE MODE means:"
    echo "  - Uses UNIX sockets instead of kernel module"
    echo "  - Service crashes don't affect system stability"
    echo "  - Automatic watchdog and recovery"
    echo "  - Graceful degradation when backends fail"
    echo ""
}

# Parse arguments
COMMAND="start"
while [[ $# -gt 0 ]]; do
    case $1 in
        --enable-kernel)
            ENABLE_KERNEL=true
            log_warn "Kernel module enabled - this is not recommended for stability"
            shift
            ;;
        --foreground)
            FOREGROUND=true
            shift
            ;;
        --debug)
            DEBUG=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        start|stop|restart|status)
            COMMAND="$1"
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# Execute
case $COMMAND in
    start)
        show_banner
        check_dependencies
        setup_directories
        start_ollama || exit 1
        ensure_model "llama2"
        start_service_daemon || exit 1
        show_status
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        exec "$0" start
        ;;
    status)
        show_status
        ;;
esac
