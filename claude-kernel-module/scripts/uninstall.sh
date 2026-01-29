#!/bin/bash
#
# Claude Kernel Module - Uninstallation Script
#
# This script removes the Claude kernel module and cleans up
# system configuration.
#
# Usage: sudo ./uninstall.sh
#

set -e

# Configuration
MODULE_NAME="claude_module"
MODULE_VERSION="1.0.0"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

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

unload_module() {
    log_info "Unloading module..."

    if lsmod | grep -q "^${MODULE_NAME} "; then
        rmmod "$MODULE_NAME"
        log_info "Module unloaded."
    else
        log_info "Module not currently loaded."
    fi
}

remove_systemd_service() {
    log_info "Removing systemd service..."

    if [[ -f /etc/systemd/system/claude-module.service ]]; then
        systemctl stop claude-module.service 2>/dev/null || true
        systemctl disable claude-module.service 2>/dev/null || true
        rm -f /etc/systemd/system/claude-module.service
        systemctl daemon-reload
        log_info "Systemd service removed."
    else
        log_info "Systemd service not found."
    fi
}

remove_dkms() {
    log_info "Checking for DKMS installation..."

    if command -v dkms &> /dev/null; then
        if dkms status -m "$MODULE_NAME" -v "$MODULE_VERSION" &> /dev/null; then
            log_info "Removing DKMS installation..."
            dkms remove -m "$MODULE_NAME" -v "$MODULE_VERSION" --all || true
            rm -rf "/usr/src/${MODULE_NAME}-${MODULE_VERSION}"
            log_info "DKMS installation removed."
        else
            log_info "No DKMS installation found."
        fi
    fi
}

remove_module_files() {
    log_info "Removing module files..."

    # Remove from kernel modules directory
    local module_path="/lib/modules/$(uname -r)/extra/${MODULE_NAME}.ko"
    if [[ -f "$module_path" ]]; then
        rm -f "$module_path"
        depmod -a
        log_info "Kernel module removed."
    fi

    # Remove header files
    if [[ -d /usr/local/include/claude ]]; then
        rm -rf /usr/local/include/claude
        log_info "Header files removed."
    fi
}

remove_udev_rules() {
    log_info "Removing udev rules..."

    if [[ -f /etc/udev/rules.d/99-claude.rules ]]; then
        rm -f /etc/udev/rules.d/99-claude.rules
        udevadm control --reload-rules 2>/dev/null || true
        log_info "Udev rules removed."
    else
        log_info "Udev rules not found."
    fi
}

cleanup_group() {
    log_info "Note: The 'claude' group has been left intact."
    log_info "To remove it manually: sudo groupdel claude"
}

main() {
    echo "========================================"
    echo "  Claude Kernel Module Uninstaller"
    echo "  Version: $MODULE_VERSION"
    echo "========================================"
    echo ""

    check_root

    unload_module
    remove_systemd_service
    remove_dkms
    remove_module_files
    remove_udev_rules
    cleanup_group

    echo ""
    log_info "Uninstallation complete!"
    echo ""
}

main
