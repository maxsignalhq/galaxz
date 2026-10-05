"""Minimal synchronous MCP client over stdio (newline-delimited JSON-RPC)."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


class McpError(RuntimeError):
    pass


class McpStdioClient:
    def __init__(self, command: list[str], env: dict[str, str] | None = None, timeout_s: float = 30.0):
        self._command = command
        self._env = env or {}
        self._timeout_s = timeout_s
        self._lock = threading.RLock()
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue | None = None
        self._next_id = 0

    # -- public API ---------------------------------------------------------

    def list_tools(self) -> list[dict]:
        tools: list[dict] = []
        cursor = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._call("tools/list", params)
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        return self._call("tools/call", {"name": name, "arguments": arguments or {}})

    def close(self) -> None:
        with self._lock:
            self._stop()

    # -- internals ----------------------------------------------------------

    def _call(self, method: str, params: dict) -> dict:
        with self._lock:
            self._ensure_started()
            return self._request(method, params)

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._stop()
        try:
            proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env={**os.environ, **self._env},
            )
        except OSError as exc:
            raise McpError(f"failed to start MCP server {self._command[0]!r}: {exc}") from exc
        inbox: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, args=(proc, inbox), daemon=True).start()
        self._proc, self._queue = proc, inbox
        self._next_id = 0
        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "galaxz-quasar", "version": "0.1.0"},
                },
            )
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except McpError:
            self._stop()
            raise

    @staticmethod
    def _read(proc: subprocess.Popen, inbox: queue.Queue) -> None:
        try:
            for line in proc.stdout:
                try:
                    inbox.put(json.loads(line))
                except ValueError:
                    continue  # ignore non-JSON noise on stdout
        finally:
            inbox.put(None)  # EOF sentinel

    def _send(self, message: dict[str, Any]) -> None:
        try:
            self._proc.stdin.write(json.dumps(message) + "\n")
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            self._stop()
            raise McpError(f"MCP server connection lost: {exc}") from exc

    def _request(self, method: str, params: dict) -> dict:
        self._next_id += 1
        rid = self._next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        deadline = time.monotonic() + self._timeout_s
        while True:
            try:
                message = self._queue.get(timeout=max(deadline - time.monotonic(), 0.001))
            except queue.Empty:
                # A late reply would be stale state, so drop the process.
                self._stop()
                raise McpError(f"MCP {method} timed out after {self._timeout_s:.1f}s") from None
            if message is None:
                self._stop()
                raise McpError("MCP server exited unexpectedly")
            if message.get("id") != rid or "method" in message:
                continue  # notification, server request, or stale reply
            if "error" in message:
                raise McpError(message["error"].get("message", "MCP error"))
            return message.get("result", {})

    def _stop(self) -> None:
        proc, self._proc, self._queue = self._proc, None, None
        if proc is None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            proc.kill()
