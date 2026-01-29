#!/bin/bash
#
# Install AI Orchestration Services
#
# This script installs and configures systemd services for:
# - Claude kernel module
# - AI Orchestrator daemon
#
# Usage: sudo ./install-services.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Check root
if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root"
    exit 1
fi

echo "=========================================="
echo "  AI Orchestration - Service Installer"
echo "=========================================="
echo ""

# Create installation directory
echo "Creating installation directory..."
mkdir -p /opt/ai-orchestration
cp -r "${PROJECT_ROOT}"/* /opt/ai-orchestration/

# Create config directory
mkdir -p /etc/ai-orchestrator
if [[ -f "${PROJECT_ROOT}/config/ai-orchestrator.json" ]]; then
    cp "${PROJECT_ROOT}/config/ai-orchestrator.json" /etc/ai-orchestrator/config.json
fi

# Create log directory
mkdir -p /var/log/ai-orchestrator
mkdir -p /var/run/ai-orchestrator

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install requests || true

# Install systemd services
echo "Installing systemd services..."
cp "${SCRIPT_DIR}/ai-orchestrator.service" /etc/systemd/system/

# Reload systemd
systemctl daemon-reload

# Enable services
echo "Enabling services..."
systemctl enable ai-orchestrator.service

echo ""
echo "Installation complete!"
echo ""
echo "To start the AI Orchestrator:"
echo "  sudo systemctl start ai-orchestrator"
echo ""
echo "To check status:"
echo "  sudo systemctl status ai-orchestrator"
echo ""
echo "View logs:"
echo "  journalctl -u ai-orchestrator -f"
echo ""
