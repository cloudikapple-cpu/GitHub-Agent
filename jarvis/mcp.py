"""Minimal MCP (Model Context Protocol) client.

Any MCP server becomes a set of Jarvis tools — GitHub, Notion, Postgres,
filesystem servers, Puppeteer, your own. Two transports are supported:

* **stdio** — ``{"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]}``
* **HTTP**  — ``{"url": "https://example.com/mcp", "headers": {...}}``

Only the three calls an agent needs are implemented: ``initialize``,
``tools/list`` and ``tools/call``. No extra dependency required.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from typing import Any

from .tools.base import Tool

LOGGER = logging.getLogger(__name__)
PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "jarvis", "version": "0.3.0"}


class MCPError(RuntimeError):
    """Raised when an MCP server cannot be reached or returns an error."""


class MCPClient:
    """Talk to a single MCP server."""

    def __init__(self, name: str, spec: dict[str, Any], timeout: int = 60) -> None:
        self.name = name
        self.spec = spec or {}
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._counter = 0
        self._lock = threading.Lock()
        self._initialised = False

    # ------------------------------------------------------------------
    @property
    def is_http(self) -> bool:
        return bool(self.spec.get("url"))

    def _next_id(self) -> int:
        self._counter += 1
        return self._counter

    # -- stdio ---------------------------------------------------------
    def _ensure_process(self) -> subprocess.Popen:
        if self._process and self._process.poll() is None:
            return self._process
        command = self.spec.get("command")
        if not command:
            raise MCPError(f"MCP server '{self.name}' has neither 'url' nor 'command'.")
        env = {**os.environ, **{str(k): str(v) for k, v in (self.spec.get("env") or {}).items()}}
        try:
            self._process = subprocess.Popen(  # noqa: S603 - user-configured server
                [command, *[str(arg) for arg in self.spec.get("args") or []]],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                env=env,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            raise MCPError(f"Cannot start MCP server '{self.name}': {exc}") from exc
        return self._process

    def _stdio_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        process = self._ensure_process()
        request_id = self._next_id()
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        }
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps(payload) + "\n")
        process.stdin.flush()

        while True:
            line = process.stdout.readline()
            if not line:
                raise MCPError(f"MCP server '{self.name}' closed the connection.")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") == request_id:
                return message

    def _notify(self, method: str) -> None:
        if self.is_http:
            return
        process = self._ensure_process()
        assert process.stdin
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        process.stdin.flush()

    # -- http ----------------------------------------------------------
    def _http_request(self, method: str, params: dict[str, Any] | None) -> dict[str, Any]:
        import requests

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **{str(k): str(v) for k, v in (self.spec.get("headers") or {}).items()},
        }
        response = requests.post(
            str(self.spec["url"]),
            json={
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": method,
                "params": params or {},
            },
            headers=headers,
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise MCPError(f"MCP server '{self.name}' returned HTTP {response.status_code}.")
        text = response.text.strip()
        if text.startswith("event:") or text.startswith("data:"):
            for line in text.splitlines():
                if line.startswith("data:"):
                    text = line[5:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise MCPError(f"MCP server '{self.name}' returned invalid JSON.") from exc

    # ------------------------------------------------------------------
    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            if not self._initialised and method != "initialize":
                self.initialize()
            message = (
                self._http_request(method, params)
                if self.is_http
                else self._stdio_request(method, params)
            )
        if "error" in message:
            error = message["error"]
            raise MCPError(f"{self.name}: {error.get('message', error)}")
        return message.get("result", {})

    def initialize(self) -> None:
        result = (
            self._http_request
            if self.is_http
            else self._stdio_request
        )(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": CLIENT_INFO,
            },
        )
        if "error" in result:
            raise MCPError(f"{self.name}: {result['error']}")
        self._initialised = True
        self._notify("notifications/initialized")

    def list_tools(self) -> list[dict[str, Any]]:
        return list((self.request("tools/list") or {}).get("tools") or [])

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        result = self.request("tools/call", {"name": tool_name, "arguments": arguments})
        chunks: list[str] = []
        for item in (result or {}).get("content") or []:
            if item.get("type") == "text":
                chunks.append(str(item.get("text", "")))
            elif item.get("type") == "resource":
                resource = item.get("resource") or {}
                chunks.append(str(resource.get("text") or resource.get("uri") or ""))
        if not chunks and result:
            chunks.append(json.dumps(result, ensure_ascii=False)[:4000])
        return "\n".join(chunk for chunk in chunks if chunk).strip() or "(empty result)"

    def close(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()


class MCPTool(Tool):
    """Expose one MCP server tool to the model."""

    category = "mcp"

    def __init__(self, client: MCPClient, spec: dict[str, Any]) -> None:
        self.client = client
        self.remote_name = str(spec.get("name", ""))
        self.name = f"{client.name}_{self.remote_name}".replace("-", "_")[:64]
        description = str(spec.get("description") or f"{self.remote_name} via MCP")
        self.description = f"[{client.name} MCP] {description}"
        self.parameters = spec.get("inputSchema") or {"type": "object", "properties": {}}
        annotations = spec.get("annotations") or {}
        self.requires_confirmation = bool(
            annotations.get("destructiveHint") or annotations.get("requiresConfirmation")
        )

    def run(self, **kwargs: Any) -> str:
        return self.client.call_tool(self.remote_name, kwargs)


def load_mcp_tools(config) -> list[Tool]:
    """Connect to every configured MCP server and return their tools.

    A server that fails to start is skipped with a warning — it must never
    prevent the assistant from running.
    """

    tools: list[Tool] = []
    for name, spec in (getattr(config, "mcp_servers", None) or {}).items():
        if spec.get("enabled") is False:
            continue
        client = MCPClient(name, spec)
        try:
            remote_tools = client.list_tools()
        except (MCPError, OSError) as exc:
            LOGGER.warning("MCP server '%s' unavailable: %s", name, exc)
            client.close()
            continue
        tools.extend(MCPTool(client, remote) for remote in remote_tools)
    return tools
