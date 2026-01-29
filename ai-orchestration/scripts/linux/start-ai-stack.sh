#!/bin/bash
#
# AI Orchestration Stack - Linux Startup Script
#
# This script starts the complete AI orchestration stack including:
# - Claude kernel module
# - Ollama server
# - AI Orchestrator daemon
#
# Usage:
#   ./start-ai-stack.sh [OPTIONS]
#
# Options:
#   --no-kernel    Skip kernel module loading
#   --no-ollama    Skip Ollama startup (assumes already running)
#   --debug        Enable debug mode
#   --foreground   Run orchestrator in foreground
#   --help         Show this help message
#

set -e

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Paths
KERNEL_MODULE_DIR="${PROJECT_ROOT}/../claude-kernel-module"
OLLAMA_WRAPPER="${PROJECT_ROOT}/ollama-wrapper"
ORCHESTRATOR="${PROJECT_ROOT}/orchestrator"
CONFIG_DIR="${PROJECT_ROOT}/config"

# Runtime paths
PID_DIR="/var/run/ai-orchestrator"
LOG_DIR="/var/log/ai-orchestrator"

# Default options
LOAD_KERNEL=true
START_OLLAMA=true
DEBUG_MODE=false
FOREGROUND=false

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    if [[ "$DEBUG_MODE" == "true" ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1"
    fi
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_warn "Not running as root - some features may not work"
        return 1
    fi
    return 0
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

wait_for_service() {
    local name="$1"
    local check_cmd="$2"
    local timeout="${3:-30}"
    local count=0

    log_info "Waiting for $name to be ready..."

    while ! eval "$check_cmd" &> /dev/null; do
        sleep 1
        count=$((count + 1))
        if [[ $count -ge $timeout ]]; then
            log_error "$name failed to start within ${timeout}s"
            return 1
        fi
        echo -n "."
    done
    echo ""
    log_info "$name is ready"
    return 0
}

# ============================================================================
# Component Functions
# ============================================================================

load_kernel_module() {
    log_info "Loading Claude kernel module..."

    # Check if already loaded
    if lsmod | grep -q "^claude_module "; then
        log_info "Kernel module already loaded"
        return 0
    fi

    # Check if module exists
    local module_ko="${KERNEL_MODULE_DIR}/claude_module.ko"
    if [[ ! -f "$module_ko" ]]; then
        log_warn "Kernel module not built. Attempting to build..."
        if [[ -f "${KERNEL_MODULE_DIR}/Makefile" ]]; then
            make -C "$KERNEL_MODULE_DIR" || {
                log_error "Failed to build kernel module"
                return 1
            }
        else
            log_error "Kernel module directory not found: $KERNEL_MODULE_DIR"
            return 1
        fi
    fi

    # Load module
    if check_root; then
        insmod "$module_ko" || {
            log_error "Failed to load kernel module"
            return 1
        }
    else
        sudo insmod "$module_ko" || {
            log_error "Failed to load kernel module (try running as root)"
            return 1
        }
    fi

    # Verify
    if [[ -c /dev/claude ]]; then
        log_info "Kernel module loaded successfully"
        log_info "Device: /dev/claude"
        return 0
    else
        log_error "Kernel module loaded but device not created"
        return 1
    fi
}

start_ollama() {
    log_info "Starting Ollama..."

    # Check if already running
    if curl -s http://localhost:11434/api/tags &> /dev/null; then
        log_info "Ollama already running"
        return 0
    fi

    # Check if ollama is installed
    if ! check_command ollama; then
        log_error "Ollama not installed. Install from: https://ollama.ai"
        return 1
    fi

    # Start Ollama
    log_info "Starting Ollama server..."

    if [[ "$FOREGROUND" == "true" ]]; then
        ollama serve &
        OLLAMA_PID=$!
    else
        nohup ollama serve > "${LOG_DIR}/ollama.log" 2>&1 &
        OLLAMA_PID=$!
        echo "$OLLAMA_PID" > "${PID_DIR}/ollama.pid"
    fi

    # Wait for Ollama to be ready
    wait_for_service "Ollama" "curl -s http://localhost:11434/api/tags" 30 || return 1

    log_info "Ollama started (PID: $OLLAMA_PID)"
    return 0
}

ensure_model() {
    local model="${1:-llama2}"

    log_info "Checking for model: $model"

    # Check if model exists
    if ollama list | grep -q "^$model"; then
        log_info "Model $model is available"
        return 0
    fi

    log_info "Pulling model: $model (this may take a while)..."
    ollama pull "$model" || {
        log_error "Failed to pull model: $model"
        return 1
    }

    return 0
}

start_orchestrator() {
    log_info "Starting AI Orchestrator..."

    # Check Python
    if ! check_command python3; then
        log_error "Python 3 not installed"
        return 1
    fi

    # Check dependencies
    python3 -c "import requests" 2>/dev/null || {
        log_warn "Installing Python dependencies..."
        pip3 install requests || {
            log_error "Failed to install dependencies"
            return 1
        }
    }

    local orchestrator_script="${ORCHESTRATOR}/ai_orchestrator.py"

    if [[ ! -f "$orchestrator_script" ]]; then
        log_error "Orchestrator script not found: $orchestrator_script"
        return 1
    fi

    local args=""
    [[ "$DEBUG_MODE" == "true" ]] && args="$args --debug"
    [[ "$LOAD_KERNEL" == "false" ]] && args="$args --no-kernel"

    if [[ "$FOREGROUND" == "true" ]]; then
        log_info "Running orchestrator in foreground..."
        python3 "$orchestrator_script" $args start
    else
        log_info "Running orchestrator as daemon..."
        nohup python3 "$orchestrator_script" $args start > "${LOG_DIR}/orchestrator.log" 2>&1 &
        local pid=$!
        echo "$pid" > "${PID_DIR}/orchestrator.pid"
        sleep 2

        if kill -0 "$pid" 2>/dev/null; then
            log_info "Orchestrator started (PID: $pid)"
        else
            log_error "Orchestrator failed to start. Check ${LOG_DIR}/orchestrator.log"
            return 1
        fi
    fi

    return 0
}

setup_directories() {
    log_debug "Setting up directories..."

    # Create directories
    mkdir -p "$PID_DIR" "$LOG_DIR" 2>/dev/null || {
        sudo mkdir -p "$PID_DIR" "$LOG_DIR"
        sudo chmod 755 "$PID_DIR" "$LOG_DIR"
    }
}

# ============================================================================
# Main Functions
# ============================================================================

show_status() {
    echo ""
    echo "=========================================="
    echo "  AI Orchestration Stack Status"
    echo "=========================================="
    echo ""

    # Kernel module
    if lsmod | grep -q "^claude_module "; then
        echo -e "Kernel Module:  ${GREEN}LOADED${NC}"
        if [[ -c /dev/claude ]]; then
            echo -e "Device:         ${GREEN}/dev/claude${NC}"
        fi
    else
        echo -e "Kernel Module:  ${YELLOW}NOT LOADED${NC}"
    fi

    # Ollama
    if curl -s http://localhost:11434/api/tags &> /dev/null; then
        echo -e "Ollama:         ${GREEN}RUNNING${NC}"
        local models=$(ollama list 2>/dev/null | tail -n +2 | wc -l)
        echo "Models:         $models available"
    else
        echo -e "Ollama:         ${RED}STOPPED${NC}"
    fi

    # Orchestrator
    if [[ -f "${PID_DIR}/orchestrator.pid" ]]; then
        local pid=$(cat "${PID_DIR}/orchestrator.pid")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "Orchestrator:   ${GREEN}RUNNING${NC} (PID: $pid)"
        else
            echo -e "Orchestrator:   ${RED}STOPPED${NC} (stale PID file)"
        fi
    else
        echo -e "Orchestrator:   ${YELLOW}NOT STARTED${NC}"
    fi

    echo ""
}

show_help() {
    echo "AI Orchestration Stack - Startup Script"
    echo ""
    echo "Usage: $0 [OPTIONS] [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start       Start all services (default)"
    echo "  stop        Stop all services"
    echo "  restart     Restart all services"
    echo "  status      Show status of all services"
    echo ""
    echo "Options:"
    echo "  --no-kernel     Skip kernel module loading"
    echo "  --no-ollama     Skip Ollama startup"
    echo "  --debug         Enable debug mode"
    echo "  --foreground    Run in foreground (don't daemonize)"
    echo "  --model MODEL   Ensure specific model is available"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start                    # Start everything"
    echo "  $0 --no-kernel start        # Start without kernel module"
    echo "  $0 --foreground start       # Run in foreground"
    echo "  $0 status                   # Check status"
    echo ""
}

stop_all() {
    log_info "Stopping AI Orchestration Stack..."

    # Stop orchestrator
    if [[ -f "${PID_DIR}/orchestrator.pid" ]]; then
        local pid=$(cat "${PID_DIR}/orchestrator.pid")
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping orchestrator (PID: $pid)..."
            kill "$pid"
            sleep 2
        fi
        rm -f "${PID_DIR}/orchestrator.pid"
    fi

    # Stop Ollama (optional - it might be used by other processes)
    if [[ -f "${PID_DIR}/ollama.pid" ]]; then
        local pid=$(cat "${PID_DIR}/ollama.pid")
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping Ollama (PID: $pid)..."
            kill "$pid"
        fi
        rm -f "${PID_DIR}/ollama.pid"
    fi

    # Unload kernel module
    if lsmod | grep -q "^claude_module "; then
        log_info "Unloading kernel module..."
        if check_root; then
            rmmod claude_module || log_warn "Failed to unload kernel module"
        else
            sudo rmmod claude_module || log_warn "Failed to unload kernel module"
        fi
    fi

    log_info "Stack stopped"
}

start_all() {
    log_info "Starting AI Orchestration Stack..."
    echo ""

    setup_directories

    # Load kernel module
    if [[ "$LOAD_KERNEL" == "true" ]]; then
        load_kernel_module || log_warn "Continuing without kernel module"
    fi

    # Start Ollama
    if [[ "$START_OLLAMA" == "true" ]]; then
        start_ollama || {
            log_error "Failed to start Ollama"
            return 1
        }

        # Ensure default model
        ensure_model "llama2" || log_warn "Default model not available"
    fi

    # Start orchestrator
    start_orchestrator || {
        log_error "Failed to start orchestrator"
        return 1
    }

    echo ""
    log_info "AI Orchestration Stack started successfully!"
    show_status
}

# ============================================================================
# Main
# ============================================================================

COMMAND="start"
MODEL=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-kernel)
            LOAD_KERNEL=false
            shift
            ;;
        --no-ollama)
            START_OLLAMA=false
            shift
            ;;
        --debug)
            DEBUG_MODE=true
            shift
            ;;
        --foreground)
            FOREGROUND=true
            shift
            ;;
        --model)
            MODEL="$2"
            shift 2
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

case $COMMAND in
    start)
        start_all
        ;;
    stop)
        stop_all
        ;;
    restart)
        stop_all
        sleep 2
        start_all
        ;;
    status)
        show_status
        ;;
esac
