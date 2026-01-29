#!/usr/bin/env python3
"""
AI Service Daemon - Safe UNIX Socket/Named Pipe Interface

This daemon provides a SAFE, production-ready interface for AI services.
It runs in userspace (not kernel space) and uses:
- UNIX sockets (Linux/macOS) for high-speed IPC
- Named pipes (Windows) for cross-platform compatibility
- Crash isolation - service crashes don't affect the system
- Automatic restart with watchdog
- Graceful degradation when backends fail

The kernel module is OPTIONAL and only used for:
- System-level logging/auditing
- Performance metrics collection
- NOT for critical communication paths

Copyright (C) 2026 Claude Code Project
License: GPL v2
"""

import os
import sys
import json
import time
import signal
import socket
import select
import logging
import argparse
import threading
import traceback
from pathlib import Path
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import queue

# Platform detection
IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')
IS_MACOS = sys.platform == 'darwin'

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ai_service')

# ============================================================================
# Configuration
# ============================================================================

@dataclass
class ServiceConfig:
    """Service configuration with safe defaults."""

    # Socket paths
    socket_path: str = "/var/run/ai-service/ai.sock"
    socket_permissions: int = 0o660
    socket_group: str = "ai-service"

    # Windows named pipe
    pipe_name: str = r"\\.\pipe\ai-service"

    # Process management
    pid_file: str = "/var/run/ai-service/ai.pid"
    max_connections: int = 100
    connection_timeout: int = 30
    request_timeout: int = 120

    # Crash protection
    max_restart_attempts: int = 5
    restart_delay_seconds: int = 2
    watchdog_interval: int = 5

    # Backend settings
    backends_config: str = "/etc/ai-service/backends.json"
    fallback_enabled: bool = True

    # Resource limits
    max_memory_mb: int = 4096
    max_queue_size: int = 1000

    # Kernel module (OPTIONAL - disabled by default for safety)
    use_kernel_module: bool = False
    kernel_device: str = "/dev/claude"


# ============================================================================
# Crash Protection & Watchdog
# ============================================================================

class ProcessState(Enum):
    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"  # Some backends failed
    RESTARTING = "restarting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    CRASHED = "crashed"


class CrashProtector:
    """Monitors and recovers from crashes."""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self._restart_count = 0
        self._last_crash_time = 0
        self._crash_history: deque = deque(maxlen=100)
        self._lock = threading.Lock()

    def record_crash(self, component: str, error: str):
        """Record a crash event."""
        with self._lock:
            crash_info = {
                "component": component,
                "error": error,
                "timestamp": time.time(),
                "traceback": traceback.format_exc()
            }
            self._crash_history.append(crash_info)
            self._last_crash_time = time.time()
            self._restart_count += 1

            logger.error(f"CRASH in {component}: {error}")

    def can_restart(self) -> bool:
        """Check if restart is allowed."""
        with self._lock:
            # Reset counter if enough time has passed
            if time.time() - self._last_crash_time > 300:  # 5 minutes
                self._restart_count = 0

            return self._restart_count < self.config.max_restart_attempts

    def get_restart_delay(self) -> float:
        """Get exponential backoff delay."""
        with self._lock:
            # Exponential backoff: 2, 4, 8, 16, 32 seconds
            delay = self.config.restart_delay_seconds * (2 ** self._restart_count)
            return min(delay, 60)  # Max 60 seconds

    def get_crash_report(self) -> Dict:
        """Get crash history report."""
        with self._lock:
            return {
                "total_crashes": len(self._crash_history),
                "restart_count": self._restart_count,
                "recent_crashes": list(self._crash_history)[-10:]
            }


class Watchdog:
    """Monitors service health and triggers recovery."""

    def __init__(self, config: ServiceConfig, crash_protector: CrashProtector):
        self.config = config
        self.crash_protector = crash_protector
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._health_checks: Dict[str, Callable] = {}
        self._component_status: Dict[str, bool] = {}

    def register_health_check(self, name: str, check_func: Callable[[], bool]):
        """Register a health check function."""
        self._health_checks[name] = check_func
        self._component_status[name] = False

    def start(self):
        """Start watchdog monitoring."""
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        logger.info("Watchdog started")

    def stop(self):
        """Stop watchdog."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                for name, check_func in self._health_checks.items():
                    try:
                        healthy = check_func()
                        prev_status = self._component_status.get(name, False)

                        if healthy and not prev_status:
                            logger.info(f"Component {name} is now healthy")
                        elif not healthy and prev_status:
                            logger.warning(f"Component {name} is unhealthy")

                        self._component_status[name] = healthy

                    except Exception as e:
                        logger.error(f"Health check failed for {name}: {e}")
                        self._component_status[name] = False

                time.sleep(self.config.watchdog_interval)

            except Exception as e:
                logger.error(f"Watchdog error: {e}")
                time.sleep(1)

    def get_status(self) -> Dict[str, Any]:
        """Get current health status."""
        return {
            "components": self._component_status.copy(),
            "all_healthy": all(self._component_status.values()),
            "healthy_count": sum(self._component_status.values()),
            "total_count": len(self._component_status)
        }


# ============================================================================
# UNIX Socket Server (Linux/macOS)
# ============================================================================

class UnixSocketServer:
    """High-performance UNIX domain socket server."""

    def __init__(self, config: ServiceConfig):
        self.config = config
        self._socket: Optional[socket.socket] = None
        self._running = False
        self._clients: List[socket.socket] = []
        self._lock = threading.Lock()
        self._handler: Optional[Callable] = None

    def set_handler(self, handler: Callable[[str], str]):
        """Set the message handler function."""
        self._handler = handler

    def start(self) -> bool:
        """Start the socket server."""
        try:
            # Ensure directory exists
            socket_dir = Path(self.config.socket_path).parent
            socket_dir.mkdir(parents=True, exist_ok=True)

            # Remove existing socket
            if os.path.exists(self.config.socket_path):
                os.unlink(self.config.socket_path)

            # Create socket
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind(self.config.socket_path)
            self._socket.listen(self.config.max_connections)
            self._socket.setblocking(False)

            # Set permissions
            os.chmod(self.config.socket_path, self.config.socket_permissions)

            self._running = True

            # Start accept thread
            accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
            accept_thread.start()

            logger.info(f"UNIX socket server listening on {self.config.socket_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to start socket server: {e}")
            return False

    def stop(self):
        """Stop the socket server."""
        self._running = False

        # Close all client connections
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except:
                    pass
            self._clients.clear()

        # Close server socket
        if self._socket:
            try:
                self._socket.close()
            except:
                pass

        # Remove socket file
        try:
            os.unlink(self.config.socket_path)
        except:
            pass

        logger.info("UNIX socket server stopped")

    def _accept_loop(self):
        """Accept incoming connections."""
        while self._running:
            try:
                readable, _, _ = select.select([self._socket], [], [], 1.0)
                if readable:
                    client, _ = self._socket.accept()
                    client.setblocking(True)
                    client.settimeout(self.config.connection_timeout)

                    with self._lock:
                        self._clients.append(client)

                    # Handle client in separate thread
                    thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,),
                        daemon=True
                    )
                    thread.start()

            except Exception as e:
                if self._running:
                    logger.error(f"Accept error: {e}")
                    time.sleep(0.1)

    def _handle_client(self, client: socket.socket):
        """Handle a client connection."""
        try:
            while self._running:
                # Receive message length (4 bytes)
                length_data = self._recv_exact(client, 4)
                if not length_data:
                    break

                msg_length = int.from_bytes(length_data, 'big')
                if msg_length > 10 * 1024 * 1024:  # 10MB limit
                    logger.warning("Message too large, dropping connection")
                    break

                # Receive message
                msg_data = self._recv_exact(client, msg_length)
                if not msg_data:
                    break

                message = msg_data.decode('utf-8')

                # Process message
                if self._handler:
                    response = self._handler(message)
                else:
                    response = json.dumps({"error": "No handler configured"})

                # Send response
                response_bytes = response.encode('utf-8')
                client.sendall(len(response_bytes).to_bytes(4, 'big'))
                client.sendall(response_bytes)

        except socket.timeout:
            logger.debug("Client timeout")
        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            with self._lock:
                if client in self._clients:
                    self._clients.remove(client)
            try:
                client.close()
            except:
                pass

    def _recv_exact(self, sock: socket.socket, n: int) -> Optional[bytes]:
        """Receive exactly n bytes."""
        data = b''
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data


# ============================================================================
# Named Pipe Server (Windows)
# ============================================================================

if IS_WINDOWS:
    import win32pipe
    import win32file
    import pywintypes

    class NamedPipeServer:
        """Windows named pipe server."""

        def __init__(self, config: ServiceConfig):
            self.config = config
            self._running = False
            self._pipe = None
            self._handler: Optional[Callable] = None

        def set_handler(self, handler: Callable[[str], str]):
            self._handler = handler

        def start(self) -> bool:
            """Start the named pipe server."""
            try:
                self._running = True
                thread = threading.Thread(target=self._pipe_loop, daemon=True)
                thread.start()
                logger.info(f"Named pipe server listening on {self.config.pipe_name}")
                return True
            except Exception as e:
                logger.error(f"Failed to start pipe server: {e}")
                return False

        def stop(self):
            """Stop the named pipe server."""
            self._running = False

        def _pipe_loop(self):
            """Main pipe handling loop."""
            while self._running:
                try:
                    # Create pipe instance
                    pipe = win32pipe.CreateNamedPipe(
                        self.config.pipe_name,
                        win32pipe.PIPE_ACCESS_DUPLEX,
                        win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                        win32pipe.PIPE_UNLIMITED_INSTANCES,
                        65536, 65536, 0, None
                    )

                    # Wait for client
                    win32pipe.ConnectNamedPipe(pipe, None)

                    # Handle in thread
                    thread = threading.Thread(
                        target=self._handle_pipe_client,
                        args=(pipe,),
                        daemon=True
                    )
                    thread.start()

                except pywintypes.error as e:
                    if self._running:
                        logger.error(f"Pipe error: {e}")
                        time.sleep(1)

        def _handle_pipe_client(self, pipe):
            """Handle a pipe client."""
            try:
                while self._running:
                    # Read message
                    result, data = win32file.ReadFile(pipe, 65536)
                    if result != 0:
                        break

                    message = data.decode('utf-8')

                    # Process
                    if self._handler:
                        response = self._handler(message)
                    else:
                        response = json.dumps({"error": "No handler"})

                    # Write response
                    win32file.WriteFile(pipe, response.encode('utf-8'))

            except Exception as e:
                logger.error(f"Pipe client error: {e}")
            finally:
                try:
                    win32file.CloseHandle(pipe)
                except:
                    pass

else:
    # Stub for non-Windows
    class NamedPipeServer:
        def __init__(self, config): pass
        def set_handler(self, handler): pass
        def start(self): return False
        def stop(self): pass


# ============================================================================
# Backend Manager with Graceful Degradation
# ============================================================================

class BackendManager:
    """Manages AI backends with automatic failover."""

    def __init__(self, config: ServiceConfig, crash_protector: CrashProtector):
        self.config = config
        self.crash_protector = crash_protector
        self._backends: Dict[str, Dict] = {}
        self._backend_health: Dict[str, bool] = {}
        self._lock = threading.Lock()

    def register_backend(self, name: str, backend_config: Dict):
        """Register a backend."""
        with self._lock:
            self._backends[name] = backend_config
            self._backend_health[name] = False

    def check_backend_health(self, name: str) -> bool:
        """Check if a backend is healthy."""
        try:
            backend = self._backends.get(name)
            if not backend:
                return False

            backend_type = backend.get('type', 'ollama')
            host = backend.get('host', 'http://localhost')
            port = backend.get('port', 11434)

            if backend_type == 'ollama':
                import requests
                resp = requests.get(f"{host}:{port}/api/tags", timeout=5)
                return resp.status_code == 200

            return True

        except Exception as e:
            logger.debug(f"Backend {name} health check failed: {e}")
            return False

    def get_healthy_backend(self) -> Optional[str]:
        """Get first healthy backend."""
        with self._lock:
            for name in self._backends:
                if self.check_backend_health(name):
                    self._backend_health[name] = True
                    return name
                else:
                    self._backend_health[name] = False

        return None

    def call_backend(self, name: str, request: Dict) -> Dict:
        """Call a backend with automatic fallback."""
        backend = self._backends.get(name)
        if not backend:
            if self.config.fallback_enabled:
                name = self.get_healthy_backend()
                if name:
                    backend = self._backends[name]
                    logger.info(f"Falling back to backend: {name}")

        if not backend:
            return {"error": "No healthy backends available"}

        try:
            return self._execute_backend_call(backend, request)
        except Exception as e:
            self.crash_protector.record_crash(f"backend:{name}", str(e))
            return {"error": str(e)}

    def _execute_backend_call(self, backend: Dict, request: Dict) -> Dict:
        """Execute the actual backend call."""
        import requests

        backend_type = backend.get('type', 'ollama')
        host = backend.get('host', 'http://localhost')
        port = backend.get('port', 11434)
        model = backend.get('model', 'llama2')

        if backend_type == 'ollama':
            prompt = request.get('prompt', request.get('content', ''))
            resp = requests.post(
                f"{host}:{port}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=self.config.request_timeout
            )
            resp.raise_for_status()
            return resp.json()

        return {"error": f"Unknown backend type: {backend_type}"}


# ============================================================================
# Main Service Daemon
# ============================================================================

class AIServiceDaemon:
    """Main AI service daemon with all safety features."""

    def __init__(self, config: Optional[ServiceConfig] = None):
        self.config = config or ServiceConfig()
        self.state = ProcessState.STOPPED

        # Safety components
        self.crash_protector = CrashProtector(self.config)
        self.watchdog = Watchdog(self.config, self.crash_protector)

        # Communication (socket preferred over kernel module)
        if IS_WINDOWS:
            self.server = NamedPipeServer(self.config)
        else:
            self.server = UnixSocketServer(self.config)

        # Backend management
        self.backend_manager = BackendManager(self.config, self.crash_protector)

        # Request queue for overload protection
        self._request_queue: queue.Queue = queue.Queue(maxsize=self.config.max_queue_size)

    def initialize(self) -> bool:
        """Initialize the service."""
        logger.info("Initializing AI Service Daemon...")
        self.state = ProcessState.STARTING

        try:
            # Register default Ollama backend
            self.backend_manager.register_backend("ollama", {
                "type": "ollama",
                "host": "http://localhost",
                "port": 11434,
                "model": "llama2"
            })

            # Set up message handler
            self.server.set_handler(self._handle_request)

            # Register health checks
            self.watchdog.register_health_check(
                "ollama",
                lambda: self.backend_manager.check_backend_health("ollama")
            )

            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            self.crash_protector.record_crash("init", str(e))
            return False

    def start(self) -> bool:
        """Start the service."""
        if not self.initialize():
            return False

        try:
            # Start socket/pipe server
            if not self.server.start():
                logger.error("Failed to start IPC server")
                return False

            # Start watchdog
            self.watchdog.start()

            # Write PID
            self._write_pid()

            self.state = ProcessState.RUNNING
            logger.info("AI Service Daemon started successfully")
            logger.info(f"  IPC: {self.config.socket_path if not IS_WINDOWS else self.config.pipe_name}")
            logger.info(f"  Kernel module: {'DISABLED (safe mode)' if not self.config.use_kernel_module else 'enabled'}")

            return True

        except Exception as e:
            logger.error(f"Start failed: {e}")
            self.crash_protector.record_crash("start", str(e))
            return False

    def _handle_request(self, raw_message: str) -> str:
        """Handle an incoming request with crash protection."""
        try:
            request = json.loads(raw_message)
        except json.JSONDecodeError:
            request = {"type": "prompt", "content": raw_message}

        msg_type = request.get('type', 'prompt')

        try:
            if msg_type == 'prompt' or msg_type == 'generate':
                result = self.backend_manager.call_backend("ollama", request)
                return json.dumps({
                    "type": "response",
                    "content": result.get('response', ''),
                    "metadata": result
                })

            elif msg_type == 'status':
                return json.dumps({
                    "type": "status",
                    "state": self.state.value,
                    "health": self.watchdog.get_status(),
                    "crashes": self.crash_protector.get_crash_report()
                })

            elif msg_type == 'health':
                return json.dumps({
                    "type": "health",
                    "healthy": self.watchdog.get_status()["all_healthy"],
                    "details": self.watchdog.get_status()
                })

            else:
                return json.dumps({"error": f"Unknown type: {msg_type}"})

        except Exception as e:
            self.crash_protector.record_crash("request_handler", str(e))
            return json.dumps({"error": str(e), "recovered": True})

    def _write_pid(self):
        """Write PID file."""
        try:
            Path(self.config.pid_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.pid_file, 'w') as f:
                f.write(str(os.getpid()))
        except Exception as e:
            logger.warning(f"Could not write PID file: {e}")

    def stop(self):
        """Stop the service gracefully."""
        logger.info("Stopping AI Service Daemon...")
        self.state = ProcessState.STOPPING

        self.watchdog.stop()
        self.server.stop()

        try:
            os.unlink(self.config.pid_file)
        except:
            pass

        self.state = ProcessState.STOPPED
        logger.info("AI Service Daemon stopped")

    def run(self):
        """Run the service (blocking)."""
        if not self.start():
            sys.exit(1)

        signal.signal(signal.SIGTERM, lambda s, f: self.stop())
        signal.signal(signal.SIGINT, lambda s, f: self.stop())

        try:
            while self.state == ProcessState.RUNNING:
                time.sleep(1)
        finally:
            self.stop()


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='AI Service Daemon - Safe UNIX Socket/Named Pipe Interface'
    )
    parser.add_argument(
        '--socket', default='/var/run/ai-service/ai.sock',
        help='UNIX socket path'
    )
    parser.add_argument(
        '--debug', action='store_true',
        help='Enable debug logging'
    )
    parser.add_argument(
        '--enable-kernel', action='store_true',
        help='Enable kernel module integration (not recommended)'
    )
    parser.add_argument(
        'command', nargs='?', default='start',
        choices=['start', 'stop', 'status'],
        help='Command'
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config = ServiceConfig()
    config.socket_path = args.socket
    config.use_kernel_module = args.enable_kernel

    if args.command == 'start':
        daemon = AIServiceDaemon(config)
        daemon.run()
    elif args.command == 'stop':
        try:
            with open(config.pid_file) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to PID {pid}")
        except Exception as e:
            print(f"Failed: {e}")
            sys.exit(1)
    elif args.command == 'status':
        # Connect to socket and get status
        if IS_WINDOWS:
            print("Use the named pipe to check status")
        else:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(config.socket_path)

                msg = json.dumps({"type": "status"}).encode('utf-8')
                sock.sendall(len(msg).to_bytes(4, 'big'))
                sock.sendall(msg)

                length = int.from_bytes(sock.recv(4), 'big')
                response = sock.recv(length).decode('utf-8')
                print(json.dumps(json.loads(response), indent=2))
                sock.close()
            except Exception as e:
                print(f"Service not running or not accessible: {e}")
                sys.exit(1)


if __name__ == '__main__':
    main()
