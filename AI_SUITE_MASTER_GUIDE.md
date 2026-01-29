# AI Orchestration Suite - Master Integration Guide

## Architecture Overview

This suite provides a **production-ready, crash-safe** AI orchestration system.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER INTERFACES                               │
├──────────────┬──────────────┬──────────────┬───────────────────────┤
│   Open WebUI │    Aider     │   Continue   │     claude-cli        │
│   (Browser)  │   (Terminal) │   (VS Code)  │     (Terminal)        │
└──────┬───────┴──────┬───────┴──────┬───────┴───────────┬───────────┘
       │              │              │                   │
       └──────────────┴──────────────┴───────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  AI Service Daemon │  ◄── UNIX Socket / Named Pipe
                    │   (Userspace)      │      (Fast, Crash-Isolated)
                    ├────────────────────┤
                    │ • Watchdog         │
                    │ • Crash Recovery   │
                    │ • Load Balancing   │
                    │ • Graceful Degrade │
                    └─────────┬──────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       │                      │                      │
┌──────▼──────┐      ┌────────▼────────┐    ┌───────▼───────┐
│   Ollama    │      │   LM Studio     │    │  Claude API   │
│ localhost:  │      │  localhost:     │    │  (Optional)   │
│   11434     │      │    1234         │    │               │
└─────────────┘      └─────────────────┘    └───────────────┘

                    ┌─────────────────────┐
                    │  Kernel Module      │  ◄── OPTIONAL (disabled by default)
                    │  /dev/claude        │      Only for logging/metrics
                    └─────────────────────┘
```

## Why UNIX Sockets Over Kernel Modules?

| Feature | UNIX Socket | Kernel Module |
|---------|-------------|---------------|
| **Crash Impact** | Service restarts | System crash/reboot |
| **Development** | Easy (Python) | Hard (C, kernel API) |
| **Debugging** | Standard tools | Kernel debugger |
| **Permissions** | User-level | Root required |
| **Performance** | Very fast | Slightly faster |
| **Safety** | ✅ Isolated | ⚠️ System-wide |

**Bottom line**: Use UNIX sockets for everything. The kernel module is optional and only for advanced metrics/logging.

---

## Quick Start Commands

### Linux (Recommended)

```bash
# SAFE startup (uses UNIX sockets, no kernel module)
./ai-orchestration/scripts/linux/start-safe.sh

# Check status
./ai-orchestration/scripts/linux/start-safe.sh status

# Stop everything
./ai-orchestration/scripts/linux/start-safe.sh stop
```

### Windows (PowerShell)

```powershell
# Quick one-click start
.\ai-orchestration\scripts\windows\Quick-Start.ps1

# Or with options
.\ai-orchestration\scripts\windows\Start-AIStack.ps1 -Model "codellama"
```

### macOS

```bash
# Install Ollama
brew install ollama

# Start with safe script
./ai-orchestration/scripts/linux/start-safe.sh
```

---

## Component Integration

### 1. Backend: Ollama (Primary)

```bash
# Start
ollama serve

# Pull models
ollama pull llama2
ollama pull codellama
ollama pull mistral

# Test
curl http://localhost:11434/api/generate -d '{
  "model": "llama2",
  "prompt": "Hello!"
}'
```

### 2. Frontend: Open WebUI

```bash
# Docker (recommended)
docker run -d -p 3000:8080 \
  -e OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  --name open-webui \
  ghcr.io/open-webui/open-webui:main

# Access at http://localhost:3000
```

### 3. Terminal Agent: Aider

```bash
# Install
pip install aider-chat

# Configure for local Ollama
export OLLAMA_API_BASE=http://127.0.0.1:11434

# Run
aider --model ollama/llama3.1
```

### 4. VS Code: Continue Extension

1. Install "Continue" extension
2. Edit `~/.continue/config.json`:

```json
{
  "models": [
    {
      "title": "Ollama",
      "provider": "ollama",
      "model": "codellama",
      "apiBase": "http://localhost:11434"
    }
  ]
}
```

---

## Service Daemon Usage

### Connect from Python

```python
from ai_client import AIClient

client = AIClient()

# Simple prompt
response = client.prompt("Explain quantum computing")
print(response)

# Check health
if client.health():
    print("Service is healthy")

# Get detailed status
status = client.status()
print(status)
```

### Connect from Bash

```bash
# Using socat
echo '{"type":"prompt","content":"Hello"}' | \
  socat - UNIX-CONNECT:/var/run/ai-service/ai.sock
```

### Connect from Any Language

The socket protocol is simple:
1. Send 4 bytes (big-endian) = message length
2. Send message (JSON UTF-8)
3. Receive 4 bytes = response length
4. Receive response (JSON UTF-8)

---

## Configuration Files

### Main Config: `/etc/ai-service/config.json`

```json
{
  "socket_path": "/var/run/ai-service/ai.sock",
  "backends": [
    {
      "name": "ollama",
      "type": "ollama",
      "host": "http://localhost",
      "port": 11434,
      "model": "llama2",
      "priority": 1
    },
    {
      "name": "lmstudio",
      "type": "openai",
      "host": "http://localhost",
      "port": 1234,
      "model": "local-model",
      "priority": 2
    }
  ],
  "fallback_enabled": true,
  "use_kernel_module": false
}
```

---

## Crash Recovery

The service daemon includes automatic crash recovery:

```
┌─────────────────────────────────────────────┐
│              WATCHDOG                        │
├─────────────────────────────────────────────┤
│  Every 5 seconds:                           │
│  1. Check backend health                    │
│  2. If unhealthy → try fallback backend     │
│  3. If service crashed → auto-restart       │
│  4. Exponential backoff: 2s, 4s, 8s...      │
│  5. Max 5 restarts, then alert              │
└─────────────────────────────────────────────┘
```

### View Crash History

```bash
# From client
python3 -c "from ai_client import AIClient; print(AIClient().status())"

# Check logs
tail -f /var/log/ai-service/ai-service.log
```

---

## Systemd Service (Production)

```bash
# Install
sudo ./ai-orchestration/scripts/linux/install-services.sh

# Manage
sudo systemctl start ai-service
sudo systemctl stop ai-service
sudo systemctl status ai-service
sudo systemctl enable ai-service  # Start on boot

# Logs
journalctl -u ai-service -f
```

---

## Security Considerations

### Socket Permissions

```bash
# Default: only owner and group can access
chmod 660 /var/run/ai-service/ai.sock

# Create service group
sudo groupadd ai-service
sudo usermod -aG ai-service $USER
```

### Network Isolation

The service only listens on a local UNIX socket, not a network port. This means:
- No remote access by default
- No firewall configuration needed
- Maximum security

To enable network access (if needed):
```python
# In config, add TCP listener
config.tcp_enabled = True
config.tcp_host = "127.0.0.1"  # localhost only
config.tcp_port = 8080
```

---

## Troubleshooting

### Service won't start

```bash
# Check logs
tail -100 /var/log/ai-service/ai-service.log

# Check socket directory permissions
ls -la /var/run/ai-service/

# Manual start with debug
python3 ai_service_daemon.py --debug start
```

### Ollama not responding

```bash
# Check if running
curl http://localhost:11434/api/tags

# Restart
pkill ollama
ollama serve

# Check logs
cat /var/log/ai-service/ollama.log
```

### Socket connection refused

```bash
# Check socket exists
ls -la /var/run/ai-service/ai.sock

# Check permissions
stat /var/run/ai-service/ai.sock

# Restart service
./start-safe.sh restart
```

---

## File Structure

```
├── ai-orchestration/
│   ├── services/
│   │   ├── ai_service_daemon.py   # Main safe daemon
│   │   └── ai_client.py           # Client library
│   ├── orchestrator/
│   │   └── ai_orchestrator.py     # Multi-backend orchestrator
│   ├── ollama-wrapper/
│   │   └── ollama_bridge.py       # Ollama integration
│   ├── scripts/
│   │   ├── linux/
│   │   │   ├── start-safe.sh      # RECOMMENDED startup
│   │   │   ├── start-ai-stack.sh  # Full startup (legacy)
│   │   │   └── install-services.sh
│   │   └── windows/
│   │       ├── Quick-Start.ps1
│   │       └── Start-AIStack.ps1
│   └── config/
│       └── ai-orchestrator.json
│
├── claude-kernel-module/          # OPTIONAL - not needed for most users
│   ├── src/
│   │   └── claude_module.c
│   └── Makefile
│
└── AI_SUITE_MASTER_GUIDE.md       # This file
```

---

## Summary: What to Use

| Use Case | Tool | Command |
|----------|------|---------|
| **Quick chat** | Ollama CLI | `ollama run llama2` |
| **Web interface** | Open WebUI | Browser → `localhost:3000` |
| **Coding assistant** | Aider | `aider --model ollama/codellama` |
| **VS Code autocomplete** | Continue | Install extension |
| **Production service** | AI Daemon | `./start-safe.sh` |
| **System metrics** | Kernel Module | Optional, experts only |

**Remember**: Always use `start-safe.sh` for production. It uses UNIX sockets which are fast AND crash-isolated.
