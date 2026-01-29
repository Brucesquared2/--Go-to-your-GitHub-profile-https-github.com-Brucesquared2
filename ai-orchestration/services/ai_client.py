#!/usr/bin/env python3
"""
AI Service Client - Connect to the AI Service Daemon

This client provides a simple interface to communicate with
the AI service daemon via UNIX sockets or named pipes.

Usage:
    from ai_client import AIClient

    client = AIClient()
    response = client.prompt("Hello, how are you?")
    print(response)
"""

import os
import sys
import json
import socket
from typing import Optional, Dict, Any

IS_WINDOWS = sys.platform == 'win32'

if IS_WINDOWS:
    import win32file
    import win32pipe


class AIClient:
    """Client for AI Service Daemon."""

    def __init__(
        self,
        socket_path: str = "/var/run/ai-service/ai.sock",
        pipe_name: str = r"\\.\pipe\ai-service",
        timeout: int = 120
    ):
        self.socket_path = socket_path
        self.pipe_name = pipe_name
        self.timeout = timeout

    def _send_request(self, request: Dict) -> Dict:
        """Send a request and get response."""
        message = json.dumps(request).encode('utf-8')

        if IS_WINDOWS:
            return self._send_via_pipe(message)
        else:
            return self._send_via_socket(message)

    def _send_via_socket(self, message: bytes) -> Dict:
        """Send via UNIX socket."""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect(self.socket_path)

            # Send length + message
            sock.sendall(len(message).to_bytes(4, 'big'))
            sock.sendall(message)

            # Receive response
            length_data = sock.recv(4)
            if not length_data:
                return {"error": "No response"}

            length = int.from_bytes(length_data, 'big')
            response_data = b''
            while len(response_data) < length:
                chunk = sock.recv(length - len(response_data))
                if not chunk:
                    break
                response_data += chunk

            return json.loads(response_data.decode('utf-8'))

        finally:
            sock.close()

    def _send_via_pipe(self, message: bytes) -> Dict:
        """Send via Windows named pipe."""
        try:
            handle = win32file.CreateFile(
                self.pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None,
                win32file.OPEN_EXISTING,
                0, None
            )

            win32file.WriteFile(handle, message)
            result, data = win32file.ReadFile(handle, 65536)
            win32file.CloseHandle(handle)

            return json.loads(data.decode('utf-8'))

        except Exception as e:
            return {"error": str(e)}

    def prompt(self, text: str, model: Optional[str] = None) -> str:
        """Send a prompt and get the response text."""
        request = {"type": "prompt", "content": text}
        if model:
            request["model"] = model

        response = self._send_request(request)

        if "error" in response:
            raise Exception(response["error"])

        return response.get("content", "")

    def generate(self, prompt: str, **kwargs) -> Dict:
        """Generate with full options."""
        request = {"type": "generate", "prompt": prompt, **kwargs}
        return self._send_request(request)

    def status(self) -> Dict:
        """Get service status."""
        return self._send_request({"type": "status"})

    def health(self) -> bool:
        """Check if service is healthy."""
        try:
            response = self._send_request({"type": "health"})
            return response.get("healthy", False)
        except:
            return False

    def is_available(self) -> bool:
        """Check if service is available."""
        try:
            if IS_WINDOWS:
                return os.path.exists(self.pipe_name.replace(r"\\.\pipe\\", ""))
            else:
                return os.path.exists(self.socket_path)
        except:
            return False


# CLI usage
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='AI Service Client')
    parser.add_argument('command', choices=['prompt', 'status', 'health'])
    parser.add_argument('text', nargs='?', default='')

    args = parser.parse_args()
    client = AIClient()

    if args.command == 'prompt':
        if not args.text:
            print("Error: prompt requires text")
            sys.exit(1)
        print(client.prompt(args.text))

    elif args.command == 'status':
        print(json.dumps(client.status(), indent=2))

    elif args.command == 'health':
        healthy = client.health()
        print("Healthy" if healthy else "Unhealthy")
        sys.exit(0 if healthy else 1)
