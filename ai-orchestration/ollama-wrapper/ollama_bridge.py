#!/usr/bin/env python3
"""
Ollama Bridge - Kernel Module Integration for Ollama

This module provides a bridge between the Claude kernel module
and Ollama, enabling kernel-level AI orchestration.

Copyright (C) 2026 Claude Code Project
License: GPL v2
"""

import os
import sys
import json
import time
import fcntl
import struct
import select
import logging
import argparse
import threading
import subprocess
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ollama_bridge')

# ============================================================================
# Kernel Module Interface
# ============================================================================

CLAUDE_DEVICE_PATH = "/dev/claude"
CLAUDE_PROC_PATH = "/proc/claude_status"

# IOCTL definitions (must match kernel module)
CLAUDE_IOC_MAGIC = ord('C')

def _IOC(dir, type, nr, size):
    return (dir << 30) | (type << 8) | nr | (size << 16)

def _IO(type, nr):
    return _IOC(0, type, nr, 0)

def _IOR(type, nr, size):
    return _IOC(2, type, nr, size)

def _IOW(type, nr, size):
    return _IOC(1, type, nr, size)

CLAUDE_IOC_RESET = _IO(CLAUDE_IOC_MAGIC, 0)
CLAUDE_IOC_GET_STATS = _IOR(CLAUDE_IOC_MAGIC, 1, 56)  # sizeof(claude_stats)
CLAUDE_IOC_SET_MODE = _IOW(CLAUDE_IOC_MAGIC, 2, 4)
CLAUDE_IOC_GET_MODE = _IOR(CLAUDE_IOC_MAGIC, 3, 4)
CLAUDE_IOC_FLUSH = _IO(CLAUDE_IOC_MAGIC, 4)
CLAUDE_IOC_GET_VERSION = _IOR(CLAUDE_IOC_MAGIC, 5, 32)


class ClaudeMode(IntEnum):
    NORMAL = 0
    DEBUG = 1
    VERBOSE = 2


@dataclass
class ClaudeStats:
    messages_sent: int = 0
    messages_received: int = 0
    bytes_written: int = 0
    bytes_read: int = 0
    errors: int = 0
    open_count: int = 0
    ioctl_count: int = 0


class KernelInterface:
    """Interface to the Claude kernel module."""

    def __init__(self, device_path: str = CLAUDE_DEVICE_PATH):
        self.device_path = device_path
        self.fd: Optional[int] = None
        self._lock = threading.Lock()

    def open(self, nonblock: bool = False) -> bool:
        """Open connection to kernel module."""
        try:
            flags = os.O_RDWR
            if nonblock:
                flags |= os.O_NONBLOCK
            self.fd = os.open(self.device_path, flags)
            logger.info(f"Opened kernel device: {self.device_path}")
            return True
        except OSError as e:
            logger.error(f"Failed to open device: {e}")
            return False

    def close(self):
        """Close connection."""
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            logger.info("Closed kernel device")

    def is_open(self) -> bool:
        """Check if connected."""
        return self.fd is not None

    def send(self, data: bytes) -> int:
        """Send data to kernel module."""
        if not self.is_open():
            raise RuntimeError("Device not open")
        with self._lock:
            return os.write(self.fd, data)

    def send_message(self, message: str) -> int:
        """Send string message."""
        return self.send(message.encode('utf-8') + b'\0')

    def recv(self, max_size: int = 4096) -> bytes:
        """Receive data from kernel module."""
        if not self.is_open():
            raise RuntimeError("Device not open")
        with self._lock:
            return os.read(self.fd, max_size)

    def recv_message(self, max_size: int = 4096) -> str:
        """Receive string message."""
        data = self.recv(max_size)
        return data.rstrip(b'\0').decode('utf-8')

    def poll(self, timeout_ms: int = 1000) -> bool:
        """Poll for data availability."""
        if not self.is_open():
            return False
        readable, _, _ = select.select([self.fd], [], [], timeout_ms / 1000.0)
        return len(readable) > 0

    def reset(self):
        """Reset device."""
        if self.is_open():
            fcntl.ioctl(self.fd, CLAUDE_IOC_RESET)

    def flush(self):
        """Flush message buffer."""
        if self.is_open():
            fcntl.ioctl(self.fd, CLAUDE_IOC_FLUSH)

    def set_mode(self, mode: ClaudeMode):
        """Set operation mode."""
        if self.is_open():
            fcntl.ioctl(self.fd, CLAUDE_IOC_SET_MODE, struct.pack('i', mode))

    def get_mode(self) -> ClaudeMode:
        """Get current mode."""
        if self.is_open():
            result = fcntl.ioctl(self.fd, CLAUDE_IOC_GET_MODE, b'\0' * 4)
            return ClaudeMode(struct.unpack('i', result)[0])
        return ClaudeMode.NORMAL

    def get_version(self) -> str:
        """Get module version."""
        if self.is_open():
            result = fcntl.ioctl(self.fd, CLAUDE_IOC_GET_VERSION, b'\0' * 32)
            return result.rstrip(b'\0').decode('utf-8')
        return "unknown"

    @staticmethod
    def is_module_loaded() -> bool:
        """Check if kernel module is loaded."""
        return os.path.exists(CLAUDE_DEVICE_PATH)


# ============================================================================
# Ollama Integration
# ============================================================================

@dataclass
class OllamaConfig:
    """Ollama configuration."""
    host: str = "http://localhost:11434"
    model: str = "llama2"
    timeout: int = 120
    context_length: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9
    repeat_penalty: float = 1.1


class OllamaClient:
    """Client for Ollama API."""

    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()
        self._session = requests.Session()

    def is_running(self) -> bool:
        """Check if Ollama is running."""
        try:
            resp = self._session.get(f"{self.config.host}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list:
        """List available models."""
        try:
            resp = self._session.get(f"{self.config.host}/api/tags", timeout=10)
            resp.raise_for_status()
            return resp.json().get('models', [])
        except requests.RequestException as e:
            logger.error(f"Failed to list models: {e}")
            return []

    def pull_model(self, model: str) -> bool:
        """Pull a model."""
        try:
            resp = self._session.post(
                f"{self.config.host}/api/pull",
                json={"name": model},
                timeout=None,
                stream=True
            )
            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    status = data.get('status', '')
                    logger.info(f"Pull status: {status}")
            return True
        except requests.RequestException as e:
            logger.error(f"Failed to pull model: {e}")
            return False

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        stream: bool = False,
        options: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Generate a response."""
        model = model or self.config.model

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": options or {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "repeat_penalty": self.config.repeat_penalty,
                "num_ctx": self.config.context_length
            }
        }

        try:
            resp = self._session.post(
                f"{self.config.host}/api/generate",
                json=payload,
                timeout=self.config.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Generation failed: {e}")
            return {"error": str(e)}

    def chat(
        self,
        messages: list,
        model: Optional[str] = None,
        stream: bool = False
    ) -> Dict[str, Any]:
        """Chat completion."""
        model = model or self.config.model

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }

        try:
            resp = self._session.post(
                f"{self.config.host}/api/chat",
                json=payload,
                timeout=self.config.timeout
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            logger.error(f"Chat failed: {e}")
            return {"error": str(e)}


# ============================================================================
# Ollama-Kernel Bridge
# ============================================================================

@dataclass
class BridgeMessage:
    """Message format for bridge communication."""
    type: str  # 'prompt', 'response', 'command', 'status'
    content: str
    model: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            'type': self.type,
            'content': self.content,
            'model': self.model,
            'metadata': self.metadata
        })

    @classmethod
    def from_json(cls, data: str) -> 'BridgeMessage':
        d = json.loads(data)
        return cls(
            type=d['type'],
            content=d['content'],
            model=d.get('model'),
            metadata=d.get('metadata', {})
        )


class OllamaBridge:
    """Bridge between kernel module and Ollama."""

    def __init__(
        self,
        kernel: Optional[KernelInterface] = None,
        ollama: Optional[OllamaClient] = None,
        config: Optional[OllamaConfig] = None
    ):
        self.kernel = kernel or KernelInterface()
        self.ollama = ollama or OllamaClient(config)
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._handlers: Dict[str, Callable] = {}

        # Register default handlers
        self._register_default_handlers()

    def _register_default_handlers(self):
        """Register default message handlers."""
        self._handlers['prompt'] = self._handle_prompt
        self._handlers['command'] = self._handle_command
        self._handlers['status'] = self._handle_status

    def register_handler(self, msg_type: str, handler: Callable):
        """Register a message handler."""
        self._handlers[msg_type] = handler

    def _handle_prompt(self, msg: BridgeMessage) -> BridgeMessage:
        """Handle prompt messages."""
        result = self.ollama.generate(
            prompt=msg.content,
            model=msg.model
        )

        if 'error' in result:
            return BridgeMessage(
                type='error',
                content=result['error'],
                metadata={'original_prompt': msg.content}
            )

        return BridgeMessage(
            type='response',
            content=result.get('response', ''),
            model=msg.model or self.ollama.config.model,
            metadata={
                'total_duration': result.get('total_duration'),
                'eval_count': result.get('eval_count')
            }
        )

    def _handle_command(self, msg: BridgeMessage) -> BridgeMessage:
        """Handle command messages."""
        cmd = msg.content.lower().strip()

        if cmd == 'list_models':
            models = self.ollama.list_models()
            return BridgeMessage(
                type='response',
                content=json.dumps([m['name'] for m in models]),
                metadata={'command': cmd}
            )
        elif cmd == 'status':
            return self._handle_status(msg)
        elif cmd.startswith('set_model '):
            new_model = cmd.split(' ', 1)[1]
            self.ollama.config.model = new_model
            return BridgeMessage(
                type='response',
                content=f'Model set to: {new_model}',
                metadata={'command': cmd}
            )
        else:
            return BridgeMessage(
                type='error',
                content=f'Unknown command: {cmd}',
                metadata={'command': cmd}
            )

    def _handle_status(self, msg: BridgeMessage) -> BridgeMessage:
        """Handle status requests."""
        status = {
            'ollama_running': self.ollama.is_running(),
            'kernel_connected': self.kernel.is_open(),
            'current_model': self.ollama.config.model,
            'bridge_running': self._running
        }

        if self.kernel.is_open():
            status['kernel_version'] = self.kernel.get_version()
            status['kernel_mode'] = self.kernel.get_mode().name

        return BridgeMessage(
            type='status',
            content=json.dumps(status),
            metadata={'timestamp': time.time()}
        )

    def process_message(self, raw_message: str) -> Optional[str]:
        """Process a message from kernel module."""
        try:
            msg = BridgeMessage.from_json(raw_message)
        except json.JSONDecodeError:
            # Treat as plain prompt
            msg = BridgeMessage(type='prompt', content=raw_message)

        handler = self._handlers.get(msg.type)
        if handler:
            response = handler(msg)
            return response.to_json()
        else:
            return BridgeMessage(
                type='error',
                content=f'Unknown message type: {msg.type}'
            ).to_json()

    def start(self, use_kernel: bool = True):
        """Start the bridge."""
        if use_kernel:
            if not self.kernel.is_module_loaded():
                logger.error("Kernel module not loaded")
                return False

            if not self.kernel.open():
                logger.error("Failed to open kernel device")
                return False

        if not self.ollama.is_running():
            logger.warning("Ollama not running - starting Ollama...")
            self._start_ollama()

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("Bridge started")
        return True

    def _start_ollama(self):
        """Attempt to start Ollama."""
        try:
            subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(3)  # Wait for startup
        except FileNotFoundError:
            logger.error("Ollama not found in PATH")

    def _run_loop(self):
        """Main processing loop."""
        while self._running:
            try:
                if self.kernel.is_open() and self.kernel.poll(timeout_ms=100):
                    message = self.kernel.recv_message()
                    if message:
                        logger.debug(f"Received: {message[:100]}...")
                        response = self.process_message(message)
                        if response:
                            self.kernel.send_message(response)
                            logger.debug(f"Sent: {response[:100]}...")
            except Exception as e:
                logger.error(f"Error in bridge loop: {e}")
                time.sleep(1)

    def stop(self):
        """Stop the bridge."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        self.kernel.close()
        logger.info("Bridge stopped")

    def send_prompt(self, prompt: str, model: Optional[str] = None) -> str:
        """Send a prompt and get response (direct mode)."""
        msg = BridgeMessage(type='prompt', content=prompt, model=model)
        response = self.process_message(msg.to_json())
        return response


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Ollama Bridge - Kernel Module Integration'
    )
    parser.add_argument(
        '--host', default='http://localhost:11434',
        help='Ollama host URL'
    )
    parser.add_argument(
        '--model', default='llama2',
        help='Default model to use'
    )
    parser.add_argument(
        '--no-kernel', action='store_true',
        help='Run without kernel module'
    )
    parser.add_argument(
        '--debug', action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        '--interactive', '-i', action='store_true',
        help='Run in interactive mode'
    )
    parser.add_argument(
        '--prompt', '-p',
        help='Single prompt to process'
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config = OllamaConfig(host=args.host, model=args.model)
    bridge = OllamaBridge(config=config)

    if args.prompt:
        # Single prompt mode
        if not bridge.ollama.is_running():
            print("Error: Ollama not running")
            sys.exit(1)

        result = bridge.send_prompt(args.prompt)
        try:
            msg = BridgeMessage.from_json(result)
            print(msg.content)
        except:
            print(result)
        return

    if args.interactive:
        # Interactive mode
        if not bridge.ollama.is_running():
            print("Error: Ollama not running")
            sys.exit(1)

        print(f"Ollama Bridge Interactive Mode (model: {config.model})")
        print("Type 'quit' to exit, 'models' to list models")
        print("-" * 50)

        while True:
            try:
                prompt = input("\nYou: ").strip()
                if not prompt:
                    continue
                if prompt.lower() == 'quit':
                    break
                if prompt.lower() == 'models':
                    models = bridge.ollama.list_models()
                    print("Available models:")
                    for m in models:
                        print(f"  - {m['name']}")
                    continue

                result = bridge.send_prompt(prompt)
                msg = BridgeMessage.from_json(result)
                print(f"\nAssistant: {msg.content}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")

        print("\nGoodbye!")
        return

    # Daemon mode
    use_kernel = not args.no_kernel

    if not bridge.start(use_kernel=use_kernel):
        sys.exit(1)

    print("Ollama Bridge running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        bridge.stop()


if __name__ == '__main__':
    main()
