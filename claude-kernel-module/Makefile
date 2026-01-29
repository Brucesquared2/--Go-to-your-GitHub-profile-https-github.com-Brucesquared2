# Claude Kernel Module - Main Makefile
#
# This Makefile builds the Claude kernel module for Linux.
#
# Usage:
#   make              - Build the kernel module
#   make clean        - Clean build artifacts
#   make install      - Install the module (requires root)
#   make uninstall    - Remove the module (requires root)
#   make load         - Load the module (requires root)
#   make unload       - Unload the module (requires root)
#   make reload       - Unload and reload the module
#   make test         - Run basic tests
#   make dkms-install - Install via DKMS
#   make dkms-remove  - Remove from DKMS

# Module name
MODULE_NAME := claude_module
MODULE_VERSION := 1.0.0

# Kernel build directory
KDIR ?= /lib/modules/$(shell uname -r)/build

# Source directory
SRC_DIR := src

# Object files
obj-m := $(MODULE_NAME).o

# Source files location
$(MODULE_NAME)-objs := src/claude_module.o

# Compiler flags
ccflags-y := -I$(src)/src -Wall -Wextra

# Default target
.PHONY: all
all: modules

# Build kernel module
.PHONY: modules
modules:
	@echo "Building Claude Kernel Module v$(MODULE_VERSION)"
	@echo "Kernel: $(shell uname -r)"
	$(MAKE) -C $(KDIR) M=$(PWD) modules

# Clean build artifacts
.PHONY: clean
clean:
	@echo "Cleaning build artifacts..."
	$(MAKE) -C $(KDIR) M=$(PWD) clean
	rm -f $(SRC_DIR)/*.o $(SRC_DIR)/.*.cmd
	rm -rf .tmp_versions Module.symvers modules.order

# Install module to system
.PHONY: install
install: modules
	@echo "Installing module..."
	$(MAKE) -C $(KDIR) M=$(PWD) modules_install
	depmod -a
	@echo "Module installed. Use 'modprobe $(MODULE_NAME)' to load."

# Uninstall module from system
.PHONY: uninstall
uninstall:
	@echo "Uninstalling module..."
	rm -f /lib/modules/$(shell uname -r)/extra/$(MODULE_NAME).ko
	depmod -a
	@echo "Module uninstalled."

# Load module
.PHONY: load
load:
	@echo "Loading module..."
	@if lsmod | grep -q "^$(MODULE_NAME) "; then \
		echo "Module already loaded."; \
	else \
		insmod $(MODULE_NAME).ko && echo "Module loaded successfully."; \
	fi
	@dmesg | tail -5

# Unload module
.PHONY: unload
unload:
	@echo "Unloading module..."
	@if lsmod | grep -q "^$(MODULE_NAME) "; then \
		rmmod $(MODULE_NAME) && echo "Module unloaded successfully."; \
	else \
		echo "Module not loaded."; \
	fi
	@dmesg | tail -3

# Reload module
.PHONY: reload
reload: unload load

# Run basic tests
.PHONY: test
test: load
	@echo "Running basic tests..."
	@echo ""
	@echo "=== Device Info ==="
	@ls -la /dev/claude 2>/dev/null || echo "Device not found"
	@echo ""
	@echo "=== Proc Status ==="
	@cat /proc/claude_status 2>/dev/null || echo "Proc entry not found"
	@echo ""
	@echo "=== Kernel Messages ==="
	@dmesg | grep claude | tail -10
	@echo ""
	@echo "Tests completed."

# DKMS installation
.PHONY: dkms-install
dkms-install:
	@echo "Installing via DKMS..."
	@mkdir -p /usr/src/$(MODULE_NAME)-$(MODULE_VERSION)
	@cp -r src Makefile dkms.conf /usr/src/$(MODULE_NAME)-$(MODULE_VERSION)/
	dkms add -m $(MODULE_NAME) -v $(MODULE_VERSION)
	dkms build -m $(MODULE_NAME) -v $(MODULE_VERSION)
	dkms install -m $(MODULE_NAME) -v $(MODULE_VERSION)
	@echo "DKMS installation complete."

# DKMS removal
.PHONY: dkms-remove
dkms-remove:
	@echo "Removing from DKMS..."
	dkms remove -m $(MODULE_NAME) -v $(MODULE_VERSION) --all || true
	rm -rf /usr/src/$(MODULE_NAME)-$(MODULE_VERSION)
	@echo "DKMS removal complete."

# Show module info
.PHONY: info
info:
	@echo "Module: $(MODULE_NAME)"
	@echo "Version: $(MODULE_VERSION)"
	@echo "Kernel: $(shell uname -r)"
	@echo "Build dir: $(KDIR)"
	@if [ -f $(MODULE_NAME).ko ]; then \
		modinfo $(MODULE_NAME).ko; \
	else \
		echo "Module not built yet."; \
	fi

# Help
.PHONY: help
help:
	@echo "Claude Kernel Module Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all           - Build the kernel module (default)"
	@echo "  clean         - Remove build artifacts"
	@echo "  install       - Install module to system (requires root)"
	@echo "  uninstall     - Remove module from system (requires root)"
	@echo "  load          - Load the module (requires root)"
	@echo "  unload        - Unload the module (requires root)"
	@echo "  reload        - Unload and reload the module"
	@echo "  test          - Run basic tests"
	@echo "  dkms-install  - Install via DKMS for automatic rebuilds"
	@echo "  dkms-remove   - Remove from DKMS"
	@echo "  info          - Show module information"
	@echo "  help          - Show this help message"
