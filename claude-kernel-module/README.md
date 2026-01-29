# Claude Kernel Module

A Linux kernel module that provides a kernel-level interface for Claude Code integration. This module creates a character device (`/dev/claude`) that enables communication between userspace applications and the kernel, along with a procfs interface for status monitoring.

## Features

- **Character Device**: `/dev/claude` for read/write communication
- **IOCTL Interface**: Control commands for mode setting, statistics, and management
- **Procfs Interface**: `/proc/claude_status` for real-time status monitoring
- **Ring Buffer**: Efficient FIFO message queue using kfifo
- **Poll/Select Support**: For async I/O operations
- **Multiple Operation Modes**: Normal, Debug, and Verbose logging
- **DKMS Support**: Automatic rebuilds on kernel updates
- **Userspace Library**: C library for easy integration
- **CLI Tool**: Command-line interface for interaction

## Requirements

- Linux kernel headers (matching your running kernel)
- GCC and build tools
- Root access for installation

### Debian/Ubuntu

```bash
sudo apt-get install linux-headers-$(uname -r) build-essential
```

### Fedora/RHEL

```bash
sudo dnf install kernel-devel kernel-headers gcc make
```

## Quick Start

### Build

```bash
cd claude-kernel-module
make
```

### Load Module

```bash
sudo make load
```

### Check Status

```bash
cat /proc/claude_status
```

### Unload Module

```bash
sudo make unload
```

## Installation

### Standard Installation

```bash
sudo ./scripts/install.sh
```

### DKMS Installation (Recommended)

DKMS automatically rebuilds the module when your kernel is updated:

```bash
sudo ./scripts/install.sh --dkms
```

### Uninstallation

```bash
sudo ./scripts/uninstall.sh
```

## Usage

### Using the CLI Tool

Build and use the command-line tool:

```bash
cd userspace
make
./claude-cli status
./claude-cli send "Hello, Claude!"
./claude-cli recv
./claude-cli monitor
./claude-cli mode debug
```

### Using the C Library

```c
#include <claude/libclaude.h>

int main() {
    // Open connection
    claude_t *handle = claude_open();
    if (!handle) {
        fprintf(stderr, "Failed to open device\n");
        return 1;
    }

    // Send a message
    claude_send_string(handle, "Hello from userspace!");

    // Receive a message
    char buffer[1024];
    ssize_t len = claude_recv_timeout(handle, buffer, sizeof(buffer), 5000);
    if (len > 0) {
        printf("Received: %s\n", buffer);
    }

    // Get statistics
    claude_stats_t stats;
    claude_get_stats(handle, &stats);
    printf("Messages sent: %lu\n", stats.messages_sent);

    // Close connection
    claude_close(handle);
    return 0;
}
```

Compile with:

```bash
gcc -o myapp myapp.c -lclaude
```

### Direct Device Access

```bash
# Write to device
echo "Hello" > /dev/claude

# Read from device
cat /dev/claude

# Check status
cat /proc/claude_status
```

## IOCTL Commands

| Command | Description |
|---------|-------------|
| `CLAUDE_IOC_RESET` | Reset device, clear buffers and statistics |
| `CLAUDE_IOC_GET_STATS` | Get current statistics |
| `CLAUDE_IOC_SET_MODE` | Set operation mode (0=normal, 1=debug, 2=verbose) |
| `CLAUDE_IOC_GET_MODE` | Get current operation mode |
| `CLAUDE_IOC_FLUSH` | Flush message buffer |
| `CLAUDE_IOC_GET_VERSION` | Get module version string |

## Project Structure

```
claude-kernel-module/
├── src/
│   ├── claude_module.c    # Main kernel module source
│   └── claude_ioctl.h     # IOCTL definitions header
├── userspace/
│   ├── libclaude.h        # Userspace library header
│   ├── libclaude.c        # Library implementation
│   ├── claude-cli.c       # CLI tool
│   └── Makefile           # Userspace build
├── scripts/
│   ├── install.sh         # Installation script
│   └── uninstall.sh       # Uninstallation script
├── Makefile               # Main kernel module Makefile
├── dkms.conf              # DKMS configuration
└── README.md              # This file
```

## Configuration

### Operation Modes

- **Normal (0)**: Standard operation with minimal logging
- **Debug (1)**: Debug messages logged to kernel log
- **Verbose (2)**: Detailed logging of all operations

Set mode via CLI:

```bash
./claude-cli mode debug
```

Or via IOCTL in code:

```c
claude_set_mode(handle, CLAUDE_MODE_DEBUG);
```

### Device Permissions

By default, the device is owned by root. To allow group access:

```bash
# Add user to claude group (created during installation)
sudo usermod -aG claude $USER
# Log out and back in for group changes to take effect
```

## Troubleshooting

### Module fails to load

Check kernel logs:

```bash
dmesg | grep claude
```

Verify kernel headers match:

```bash
uname -r
ls /lib/modules/$(uname -r)/build
```

### Permission denied on /dev/claude

Either run as root or add yourself to the claude group:

```bash
sudo usermod -aG claude $USER
```

### Device not created

Check if udev rules are in place:

```bash
cat /etc/udev/rules.d/99-claude.rules
```

Reload udev:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Development

### Building with Debug Symbols

```bash
make CFLAGS="-g -DDEBUG"
```

### Running Tests

```bash
sudo make test
```

### View Kernel Logs

```bash
dmesg -w | grep claude
```

## License

GPL v2 - See LICENSE file for details.

## Contributing

Contributions are welcome! Please submit pull requests or open issues on GitHub.

## Author

Claude Code Project
