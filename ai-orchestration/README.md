# AI Orchestration Stack

A complete AI orchestration system that integrates multiple AI backends (Ollama, Claude API, etc.) with optional Linux kernel module support for system-level AI integration.

## Quick Start

### Windows (Easiest)

1. Install [Ollama](https://ollama.ai/download/windows)
2. Double-click `scripts/windows/start.bat`

Or in PowerShell:
```powershell
# Allow script execution (one-time)
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Start the stack
.\scripts\windows\Quick-Start.ps1
```

### Linux

```bash
# Install Ollama first
curl -fsSL https://ollama.ai/install.sh | sh

# Start the AI stack
./scripts/linux/start-ai-stack.sh
```

### macOS

```bash
# Install Ollama
brew install ollama

# Start Ollama
ollama serve &

# Pull a model
ollama pull llama2

# Test it
ollama run llama2 "Hello!"
```

## What's Included

```
ai-orchestration/
├── ollama-wrapper/          # Python wrapper for Ollama + kernel integration
│   └── ollama_bridge.py     # Main bridge module
├── orchestrator/            # Central AI management daemon
│   └── ai_orchestrator.py   # Orchestrator service
├── scripts/
│   ├── linux/              # Linux startup scripts
│   │   ├── start-ai-stack.sh
│   │   ├── ai-orchestrator.service
│   │   └── install-services.sh
│   └── windows/            # Windows startup scripts
│       ├── Start-AIStack.ps1
│       ├── Quick-Start.ps1
│       └── start.bat
└── config/                  # Configuration files
    ├── ai-orchestrator.json
    └── environment.example
```

## Commands Reference

### Linux Commands

```bash
# Start everything (Ollama + Orchestrator + Kernel Module)
sudo ./scripts/linux/start-ai-stack.sh

# Start without kernel module
./scripts/linux/start-ai-stack.sh --no-kernel

# Check status
./scripts/linux/start-ai-stack.sh status

# Stop all services
sudo ./scripts/linux/start-ai-stack.sh stop

# Run in foreground (for debugging)
./scripts/linux/start-ai-stack.sh --foreground --debug
```

### Windows PowerShell Commands

```powershell
# Start everything
.\scripts\windows\Start-AIStack.ps1

# Start with specific model
.\scripts\windows\Start-AIStack.ps1 -Model "codellama"

# Check status
.\scripts\windows\Start-AIStack.ps1 status

# Stop all services
.\scripts\windows\Start-AIStack.ps1 stop

# Run in foreground with debug
.\scripts\windows\Start-AIStack.ps1 -Foreground -Debug
```

### Ollama Direct Commands

```bash
# Start Ollama server
ollama serve

# List available models
ollama list

# Pull a model
ollama pull llama2
ollama pull codellama
ollama pull mistral

# Run interactive chat
ollama run llama2

# Run with a prompt
ollama run llama2 "Explain quantum computing"

# API request (curl)
curl http://localhost:11434/api/generate -d '{
  "model": "llama2",
  "prompt": "Hello!",
  "stream": false
}'
```

### PowerShell API Requests

```powershell
# Simple generation
$response = Invoke-RestMethod -Uri "http://localhost:11434/api/generate" -Method Post -Body (@{
    model = "llama2"
    prompt = "Hello, how are you?"
    stream = $false
} | ConvertTo-Json) -ContentType "application/json"

$response.response

# Chat completion
$response = Invoke-RestMethod -Uri "http://localhost:11434/api/chat" -Method Post -Body (@{
    model = "llama2"
    messages = @(
        @{ role = "user"; content = "What is the capital of France?" }
    )
    stream = $false
} | ConvertTo-Json -Depth 3) -ContentType "application/json"

$response.message.content
```

## Systemd Service Installation (Linux)

```bash
# Install services
sudo ./scripts/linux/install-services.sh

# Manage with systemctl
sudo systemctl start ai-orchestrator
sudo systemctl stop ai-orchestrator
sudo systemctl status ai-orchestrator
sudo systemctl enable ai-orchestrator  # Start on boot

# View logs
journalctl -u ai-orchestrator -f
```

## Configuration

Edit `config/ai-orchestrator.json`:

```json
{
  "default_backend": "ollama",
  "backends": [
    {
      "name": "ollama",
      "type": "ollama",
      "enabled": true,
      "host": "http://localhost",
      "port": 11434,
      "model": "llama2"
    }
  ]
}
```

### Environment Variables

```bash
# Set Ollama host
export OLLAMA_HOST=http://localhost:11434

# Claude API (optional)
export ANTHROPIC_API_KEY=sk-ant-...
```

## Integration with Claude Kernel Module

On Linux, the orchestrator can integrate with the Claude kernel module for system-level AI access:

```bash
# Load kernel module first
cd ../claude-kernel-module
sudo make load

# Start orchestrator with kernel support
./scripts/linux/start-ai-stack.sh

# Messages sent to /dev/claude are processed by Ollama
echo '{"type":"prompt","content":"Hello!"}' > /dev/claude
cat /dev/claude  # Read response
```

## Troubleshooting

### Ollama won't start

```bash
# Check if port is in use
netstat -tlnp | grep 11434
lsof -i :11434

# Kill existing process
pkill ollama

# Start fresh
ollama serve
```

### Model download fails

```bash
# Check disk space
df -h

# Try different model
ollama pull tinyllama  # Smaller model
```

### PowerShell execution policy error

```powershell
# Run as Administrator
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Or bypass for single script
powershell -ExecutionPolicy Bypass -File script.ps1
```

### Permission denied on Linux

```bash
# Run with sudo
sudo ./scripts/linux/start-ai-stack.sh

# Or add user to docker group (if using Docker)
sudo usermod -aG docker $USER
```

## Supported Models

| Model | Size | Best For |
|-------|------|----------|
| llama2 | 7B | General purpose |
| llama2:13b | 13B | Better quality |
| codellama | 7B | Code generation |
| mistral | 7B | Fast, efficient |
| mixtral | 47B | High quality |
| phi | 2.7B | Lightweight |

Pull any model:
```bash
ollama pull <model-name>
```

## License

GPL v2 - See LICENSE file for details.
