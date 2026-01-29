#!/usr/bin/env python3
"""
AI Orchestrator - Central AI Management Daemon

This orchestrator manages multiple AI backends (Ollama, Claude API, etc.)
and provides unified access through the kernel module interface.

Copyright (C) 2026 Claude Code Project
License: GPL v2
"""

import os
import sys
import json
import time
import signal
import logging
import argparse
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field, asdict
from enum import Enum
from abc import ABC, abstractmethod
import socket

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'ollama-wrapper'))

try:
    from ollama_bridge import OllamaBridge, OllamaConfig, KernelInterface
except ImportError:
    OllamaBridge = None

try:
    import requests
except ImportError:
    requests = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ai_orchestrator')

# ============================================================================
# Configuration
# ============================================================================

CONFIG_PATHS = [
    Path('/etc/ai-orchestrator/config.json'),
    Path.home() / '.config/ai-orchestrator/config.json',
    Path('./config/ai-orchestrator.json'),
]


@dataclass
class BackendConfig:
    """Configuration for an AI backend."""
    name: str
    type: str  # 'ollama', 'claude', 'openai', 'local'
    enabled: bool = True
    host: str = ""
    port: int = 0
    model: str = ""
    api_key: str = ""
    priority: int = 1
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorConfig:
    """Main orchestrator configuration."""
    # General settings
    log_level: str = "INFO"
    pid_file: str = "/var/run/ai-orchestrator.pid"
    socket_path: str = "/var/run/ai-orchestrator.sock"

    # Kernel module settings
    use_kernel_module: bool = True
    kernel_device: str = "/dev/claude"

    # Backend configurations
    backends: List[BackendConfig] = field(default_factory=list)

    # Routing settings
    default_backend: str = "ollama"
    fallback_enabled: bool = True

    # Performance settings
    max_concurrent: int = 4
    request_timeout: int = 120
    queue_size: int = 100

    @classmethod
    def load(cls, path: Optional[Path] = None) -> 'OrchestratorConfig':
        """Load configuration from file."""
        if path and path.exists():
            with open(path) as f:
                data = json.load(f)
            return cls._from_dict(data)

        for config_path in CONFIG_PATHS:
            if config_path.exists():
                with open(config_path) as f:
                    data = json.load(f)
                return cls._from_dict(data)

        return cls()

    @classmethod
    def _from_dict(cls, data: Dict) -> 'OrchestratorConfig':
        """Create config from dictionary."""
        backends = [
            BackendConfig(**b) for b in data.pop('backends', [])
        ]
        return cls(backends=backends, **data)

    def save(self, path: Path):
        """Save configuration to file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)


# ============================================================================
# AI Backend Interface
# ============================================================================

class BackendStatus(Enum):
    UNKNOWN = "unknown"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class AIBackend(ABC):
    """Abstract base class for AI backends."""

    def __init__(self, config: BackendConfig):
        self.config = config
        self._status = BackendStatus.UNKNOWN
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def status(self) -> BackendStatus:
        return self._status

    @abstractmethod
    def start(self) -> bool:
        """Start the backend."""
        pass

    @abstractmethod
    def stop(self) -> bool:
        """Stop the backend."""
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if backend is healthy."""
        pass

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate a response."""
        pass

    @abstractmethod
    def chat(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Chat completion."""
        pass


class OllamaBackend(AIBackend):
    """Ollama backend implementation."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self.host = config.host or "http://localhost"
        self.port = config.port or 11434
        self.base_url = f"{self.host}:{self.port}"
        self._process: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        """Start Ollama server."""
        if self.is_healthy():
            self._status = BackendStatus.RUNNING
            return True

        self._status = BackendStatus.STARTING
        try:
            self._process = subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, 'OLLAMA_HOST': f'0.0.0.0:{self.port}'}
            )
            time.sleep(3)

            if self.is_healthy():
                self._status = BackendStatus.RUNNING
                logger.info(f"Ollama backend started on {self.base_url}")
                return True
            else:
                self._status = BackendStatus.ERROR
                return False
        except Exception as e:
            logger.error(f"Failed to start Ollama: {e}")
            self._status = BackendStatus.ERROR
            return False

    def stop(self) -> bool:
        """Stop Ollama server."""
        if self._process:
            self._process.terminate()
            self._process.wait(timeout=10)
            self._process = None
        self._status = BackendStatus.STOPPED
        return True

    def is_healthy(self) -> bool:
        """Check if Ollama is running."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except:
            return False

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate response."""
        model = kwargs.get('model', self.config.model or 'llama2')
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": self.config.options
                },
                timeout=self.config.options.get('timeout', 120)
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}

    def chat(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Chat completion."""
        model = kwargs.get('model', self.config.model or 'llama2')
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False
                },
                timeout=self.config.options.get('timeout', 120)
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


class ClaudeAPIBackend(AIBackend):
    """Claude API backend implementation."""

    def __init__(self, config: BackendConfig):
        super().__init__(config)
        self.api_key = config.api_key or os.environ.get('ANTHROPIC_API_KEY', '')
        self.base_url = config.host or "https://api.anthropic.com"

    def start(self) -> bool:
        """Validate API access."""
        if not self.api_key:
            logger.error("Claude API key not configured")
            self._status = BackendStatus.ERROR
            return False

        if self.is_healthy():
            self._status = BackendStatus.RUNNING
            return True

        self._status = BackendStatus.ERROR
        return False

    def stop(self) -> bool:
        self._status = BackendStatus.STOPPED
        return True

    def is_healthy(self) -> bool:
        """Check API access."""
        if not self.api_key:
            return False
        # Could add a lightweight API check here
        return True

    def generate(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate using Claude API."""
        return self.chat([{"role": "user", "content": prompt}], **kwargs)

    def chat(self, messages: List[Dict], **kwargs) -> Dict[str, Any]:
        """Chat with Claude API."""
        model = kwargs.get('model', self.config.model or 'claude-3-sonnet-20240229')
        try:
            resp = requests.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": model,
                    "max_tokens": kwargs.get('max_tokens', 4096),
                    "messages": messages
                },
                timeout=self.config.options.get('timeout', 120)
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"error": str(e)}


# ============================================================================
# Orchestrator
# ============================================================================

class AIOrchestrator:
    """Main AI Orchestrator daemon."""

    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self.config = config or OrchestratorConfig()
        self._running = False
        self._backends: Dict[str, AIBackend] = {}
        self._kernel: Optional[KernelInterface] = None
        self._threads: List[threading.Thread] = []
        self._request_queue = []
        self._lock = threading.Lock()

    def _create_backend(self, config: BackendConfig) -> Optional[AIBackend]:
        """Create backend instance from config."""
        backend_types = {
            'ollama': OllamaBackend,
            'claude': ClaudeAPIBackend,
        }

        backend_class = backend_types.get(config.type)
        if backend_class:
            return backend_class(config)

        logger.warning(f"Unknown backend type: {config.type}")
        return None

    def initialize(self) -> bool:
        """Initialize the orchestrator."""
        logger.info("Initializing AI Orchestrator...")

        # Set up logging
        logging.getLogger().setLevel(getattr(logging, self.config.log_level))

        # Initialize backends
        for backend_config in self.config.backends:
            if not backend_config.enabled:
                continue

            backend = self._create_backend(backend_config)
            if backend:
                self._backends[backend_config.name] = backend
                logger.info(f"Registered backend: {backend_config.name}")

        # Add default Ollama backend if none configured
        if not self._backends:
            default_config = BackendConfig(
                name="ollama",
                type="ollama",
                model="llama2"
            )
            self._backends["ollama"] = OllamaBackend(default_config)
            logger.info("Added default Ollama backend")

        # Initialize kernel module interface
        if self.config.use_kernel_module and KernelInterface:
            self._kernel = KernelInterface(self.config.kernel_device)

        return True

    def start(self) -> bool:
        """Start the orchestrator."""
        if not self.initialize():
            return False

        logger.info("Starting AI Orchestrator...")
        self._running = True

        # Start backends
        for name, backend in self._backends.items():
            if backend.config.enabled:
                logger.info(f"Starting backend: {name}")
                if not backend.start():
                    logger.warning(f"Failed to start backend: {name}")

        # Connect to kernel module
        if self._kernel:
            if KernelInterface.is_module_loaded():
                if self._kernel.open():
                    logger.info("Connected to kernel module")
                    # Start kernel message handler
                    t = threading.Thread(target=self._kernel_handler, daemon=True)
                    t.start()
                    self._threads.append(t)
                else:
                    logger.warning("Failed to open kernel device")
            else:
                logger.warning("Kernel module not loaded")

        # Write PID file
        self._write_pid()

        logger.info("AI Orchestrator started successfully")
        return True

    def _kernel_handler(self):
        """Handle messages from kernel module."""
        while self._running and self._kernel and self._kernel.is_open():
            try:
                if self._kernel.poll(timeout_ms=100):
                    message = self._kernel.recv_message()
                    if message:
                        response = self._process_request(message)
                        self._kernel.send_message(response)
            except Exception as e:
                logger.error(f"Kernel handler error: {e}")
                time.sleep(1)

    def _process_request(self, request: str) -> str:
        """Process an incoming request."""
        try:
            data = json.loads(request)
        except json.JSONDecodeError:
            data = {"type": "prompt", "content": request}

        msg_type = data.get('type', 'prompt')
        content = data.get('content', '')
        backend_name = data.get('backend', self.config.default_backend)

        if msg_type == 'prompt' or msg_type == 'generate':
            return self._handle_generate(content, backend_name, data)
        elif msg_type == 'chat':
            return self._handle_chat(data.get('messages', []), backend_name, data)
        elif msg_type == 'status':
            return self._handle_status()
        elif msg_type == 'command':
            return self._handle_command(content)
        else:
            return json.dumps({"error": f"Unknown request type: {msg_type}"})

    def _handle_generate(self, prompt: str, backend_name: str, options: Dict) -> str:
        """Handle generate request."""
        backend = self._get_backend(backend_name)
        if not backend:
            return json.dumps({"error": f"Backend not available: {backend_name}"})

        result = backend.generate(prompt, **options)
        return json.dumps({
            "type": "response",
            "backend": backend_name,
            "content": result.get('response', result.get('content', '')),
            "metadata": result
        })

    def _handle_chat(self, messages: List[Dict], backend_name: str, options: Dict) -> str:
        """Handle chat request."""
        backend = self._get_backend(backend_name)
        if not backend:
            return json.dumps({"error": f"Backend not available: {backend_name}"})

        result = backend.chat(messages, **options)
        return json.dumps({
            "type": "response",
            "backend": backend_name,
            "content": result.get('message', {}).get('content', ''),
            "metadata": result
        })

    def _handle_status(self) -> str:
        """Handle status request."""
        status = {
            "running": self._running,
            "kernel_connected": self._kernel.is_open() if self._kernel else False,
            "backends": {}
        }

        for name, backend in self._backends.items():
            status["backends"][name] = {
                "status": backend.status.value,
                "healthy": backend.is_healthy(),
                "model": backend.config.model
            }

        return json.dumps({"type": "status", "content": status})

    def _handle_command(self, command: str) -> str:
        """Handle command request."""
        parts = command.split()
        cmd = parts[0].lower() if parts else ''

        if cmd == 'list_backends':
            return json.dumps({
                "type": "response",
                "content": list(self._backends.keys())
            })
        elif cmd == 'health':
            health = {name: b.is_healthy() for name, b in self._backends.items()}
            return json.dumps({"type": "response", "content": health})
        else:
            return json.dumps({"error": f"Unknown command: {cmd}"})

    def _get_backend(self, name: str) -> Optional[AIBackend]:
        """Get a backend by name, with fallback."""
        backend = self._backends.get(name)

        if backend and backend.is_healthy():
            return backend

        if self.config.fallback_enabled:
            # Try other backends by priority
            sorted_backends = sorted(
                self._backends.values(),
                key=lambda b: b.config.priority
            )
            for b in sorted_backends:
                if b.is_healthy():
                    logger.info(f"Falling back to backend: {b.name}")
                    return b

        return None

    def _write_pid(self):
        """Write PID file."""
        try:
            Path(self.config.pid_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.pid_file, 'w') as f:
                f.write(str(os.getpid()))
        except:
            pass

    def _remove_pid(self):
        """Remove PID file."""
        try:
            os.remove(self.config.pid_file)
        except:
            pass

    def stop(self):
        """Stop the orchestrator."""
        logger.info("Stopping AI Orchestrator...")
        self._running = False

        # Stop backends
        for name, backend in self._backends.items():
            logger.info(f"Stopping backend: {name}")
            backend.stop()

        # Close kernel connection
        if self._kernel:
            self._kernel.close()

        # Wait for threads
        for t in self._threads:
            t.join(timeout=5)

        self._remove_pid()
        logger.info("AI Orchestrator stopped")

    def run(self):
        """Run the orchestrator (blocking)."""
        if not self.start():
            sys.exit(1)

        # Set up signal handlers
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())
        signal.signal(signal.SIGINT, lambda s, f: self.stop())

        try:
            while self._running:
                time.sleep(1)
        finally:
            self.stop()


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='AI Orchestrator - Central AI Management Daemon'
    )
    parser.add_argument(
        '-c', '--config',
        type=Path,
        help='Path to configuration file'
    )
    parser.add_argument(
        '-d', '--daemon',
        action='store_true',
        help='Run as daemon'
    )
    parser.add_argument(
        '--no-kernel',
        action='store_true',
        help='Run without kernel module'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        'command',
        nargs='?',
        choices=['start', 'stop', 'status', 'restart'],
        default='start',
        help='Command to execute'
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config = OrchestratorConfig.load(args.config)

    if args.no_kernel:
        config.use_kernel_module = False

    if args.command == 'start':
        orchestrator = AIOrchestrator(config)
        orchestrator.run()
    elif args.command == 'stop':
        try:
            with open(config.pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to PID {pid}")
        except Exception as e:
            print(f"Failed to stop: {e}")
            sys.exit(1)
    elif args.command == 'status':
        try:
            with open(config.pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            print(f"AI Orchestrator is running (PID: {pid})")
        except:
            print("AI Orchestrator is not running")
    elif args.command == 'restart':
        # Stop then start
        try:
            with open(config.pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
        except:
            pass
        orchestrator = AIOrchestrator(config)
        orchestrator.run()


if __name__ == '__main__':
    main()
