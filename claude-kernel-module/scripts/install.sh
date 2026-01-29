#!/bin/bash
#
# Claude Kernel Module - Installation Script
#
# This script installs the Claude kernel module and sets up
# the necessary system configuration for Debian/Ubuntu systems.
#
# Usage: sudo ./install.sh [--dkms]
#
# Options:
#   --dkms    Install using DKMS for automatic kernel update rebuilds
#

set -e

# Configuration
MODULE_NAME="claude_module"
MODULE_VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "This script must be run as root"
        exit 1
    fi
}

check_dependencies() {
    log_info "Checking dependencies..."

    local missing_deps=()

    # Check for kernel headers
    if [[ ! -d "/lib/modules/$(uname -r)/build" ]]; then
        missing_deps+=("linux-headers-$(uname -r)")
    fi

    # Check for build tools
    if ! command -v make &> /dev/null; then
        missing_deps+=("build-essential")
    fi

    # Check for gcc
    if ! command -v gcc &> /dev/null; then
        missing_deps+=("gcc")
    fi

    # Check for DKMS if requested
    if [[ "$USE_DKMS" == "true" ]]; then
        if ! command -v dkms &> /dev/null; then
            missing_deps+=("dkms")
        fi
    fi

    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log_warn "Missing dependencies: ${missing_deps[*]}"
        log_info "Installing dependencies..."

        if command -v apt-get &> /dev/null; then
            apt-get update
            apt-get install -y "${missing_deps[@]}"
        elif command -v dnf &> /dev/null; then
            dnf install -y "${missing_deps[@]}"
        elif command -v yum &> /dev/null; then
            yum install -y "${missing_deps[@]}"
        else
            log_error "Unable to install dependencies. Please install manually: ${missing_deps[*]}"
            exit 1
        fi
    fi

    log_info "All dependencies satisfied."
}

build_module() {
    log_info "Building kernel module..."
    cd "$PROJECT_DIR"
    make clean
    make
    log_info "Build complete."
}

install_standard() {
    log_info "Installing module (standard method)..."

    cd "$PROJECT_DIR"

    # Install module
    make install

    # Copy header to include directory
    mkdir -p /usr/local/include/claude
    cp src/claude_ioctl.h /usr/local/include/claude/

    # Set up udev rules for device permissions
    cat > /etc/udev/rules.d/99-claude.rules << 'EOF'
# Claude Kernel Module udev rules
# Allow users in the 'claude' group to access the device
KERNEL=="claude", MODE="0660", GROUP="claude"
EOF

    # Create claude group if it doesn't exist
    if ! getent group claude &> /dev/null; then
        groupadd claude
        log_info "Created 'claude' group"
    fi

    # Reload udev rules
    udevadm control --reload-rules
    udevadm trigger

    log_info "Standard installation complete."
}

install_dkms() {
    log_info "Installing module via DKMS..."

    local dkms_dir="/usr/src/${MODULE_NAME}-${MODULE_VERSION}"

    # Remove existing DKMS installation if present
    if dkms status -m "$MODULE_NAME" -v "$MODULE_VERSION" &> /dev/null; then
        log_info "Removing existing DKMS installation..."
        dkms remove -m "$MODULE_NAME" -v "$MODULE_VERSION" --all || true
    fi

    # Create DKMS source directory
    rm -rf "$dkms_dir"
    mkdir -p "$dkms_dir"

    # Copy source files
    cp -r "$PROJECT_DIR/src" "$dkms_dir/"
    cp "$PROJECT_DIR/Makefile" "$dkms_dir/"
    cp "$PROJECT_DIR/dkms.conf" "$dkms_dir/"

    # Register with DKMS
    dkms add -m "$MODULE_NAME" -v "$MODULE_VERSION"
    dkms build -m "$MODULE_NAME" -v "$MODULE_VERSION"
    dkms install -m "$MODULE_NAME" -v "$MODULE_VERSION"

    # Copy header to include directory
    mkdir -p /usr/local/include/claude
    cp src/claude_ioctl.h /usr/local/include/claude/

    # Set up udev rules
    cat > /etc/udev/rules.d/99-claude.rules << 'EOF'
# Claude Kernel Module udev rules
KERNEL=="claude", MODE="0660", GROUP="claude"
EOF

    # Create claude group if it doesn't exist
    if ! getent group claude &> /dev/null; then
        groupadd claude
        log_info "Created 'claude' group"
    fi

    # Reload udev rules
    udevadm control --reload-rules
    udevadm trigger

    log_info "DKMS installation complete."
}

install_systemd_service() {
    log_info "Installing systemd service..."

    cat > /etc/systemd/system/claude-module.service << EOF
[Unit]
Description=Claude Kernel Module
After=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/modprobe $MODULE_NAME
ExecStop=/sbin/rmmod $MODULE_NAME

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable claude-module.service

    log_info "Systemd service installed and enabled."
}

load_module() {
    log_info "Loading module..."

    if lsmod | grep -q "^${MODULE_NAME} "; then
        log_warn "Module already loaded."
    else
        modprobe "$MODULE_NAME" || insmod "${PROJECT_DIR}/${MODULE_NAME}.ko"
        log_info "Module loaded successfully."
    fi

    # Display module info
    log_info "Module status:"
    echo ""
    cat /proc/claude_status 2>/dev/null || log_warn "Proc entry not available"
    echo ""
    log_info "Device: /dev/claude"
    ls -la /dev/claude 2>/dev/null || log_warn "Device not created"
}

print_usage() {
    echo "Claude Kernel Module Installation Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --dkms        Install using DKMS for automatic kernel rebuilds"
    echo "  --no-service  Don't install systemd service"
    echo "  --no-load     Don't load module after installation"
    echo "  -h, --help    Show this help message"
}

# Parse arguments
USE_DKMS="false"
INSTALL_SERVICE="true"
LOAD_MODULE="true"

while [[ $# -gt 0 ]]; do
    case $1 in
        --dkms)
            USE_DKMS="true"
            shift
            ;;
        --no-service)
            INSTALL_SERVICE="false"
            shift
            ;;
        --no-load)
            LOAD_MODULE="false"
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            print_usage
            exit 1
            ;;
    esac
done

# Main installation
main() {
    echo "========================================"
    echo "  Claude Kernel Module Installer"
    echo "  Version: $MODULE_VERSION"
    echo "========================================"
    echo ""

    check_root
    check_dependencies

    if [[ "$USE_DKMS" == "true" ]]; then
        install_dkms
    else
        build_module
        install_standard
    fi

    if [[ "$INSTALL_SERVICE" == "true" ]]; then
        install_systemd_service
    fi

    if [[ "$LOAD_MODULE" == "true" ]]; then
        load_module
    fi

    echo ""
    log_info "Installation complete!"
    echo ""
    echo "To add a user to the claude group:"
    echo "  sudo usermod -aG claude <username>"
    echo ""
    echo "To check module status:"
    echo "  cat /proc/claude_status"
    echo ""
}

main
