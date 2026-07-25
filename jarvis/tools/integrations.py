"""Integrations with other applications and services.

``http_request`` is a generic REST client: it can call any HTTP API directly,
or use a **named service** declared in ``config.yaml``::

    integrations:
      notion:
        base_url: https://api.notion.com/v1
        headers:
          Authorization: Bearer ${NOTION_TOKEN}
          Notion-Version: "2022-06-28"
      home_assistant:
        base_url: http://homeassistant.local:8123/api
        headers:
          Authorization: Bearer ${HASS_TOKEN}

The model then calls ``http_request(service="notion", path="/search", ...)``
without ever seeing the token.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from ..clipboard import ClipboardHistory, ClipboardUnavailable, read_clipboard, write_clipboard
from ..security import SecurityError, SecurityPolicy
from .base import Tool

_MAX_BODY = 12_000


class HttpRequestTool(Tool):
    name = "http_request"
    description = (
        "Call an HTTP/REST API. Either pass a full url, or a configured service "
        "name plus a path. Returns the status code and response body."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "description": "HTTP method.",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
            },
            "service": {"type": "string", "description": "Name of a configured integration."},
            "path": {"type": "string", "description": "Path appended to the service base_url."},
            "url": {"type": "string", "description": "Full URL (when not using a service)."},
            "params": {"type": "object", "description": "Query string parameters."},
            "json_body": {"type": "object", "description": "JSON request body."},
            "headers": {"type": "object", "description": "Extra request headers."},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30).", "default": 30},
        },
    }

    def __init__(
        self,
        services: dict[str, dict[str, Any]] | None = None,
        policy: SecurityPolicy | None = None,
    ):
        self.services = services or {}
        self.policy = policy or SecurityPolicy()
        if self.services:
            self.description += " Configured services: " + ", ".join(sorted(self.services)) + "."

    def run(
        self,
        method: str = "GET",
        service: str | None = None,
        path: str = "",
        url: str | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
    ) -> str:
        try:
            self.policy.check_network()
        except SecurityError as exc:
            return f"Refused: {exc}"

        request_headers: dict[str, str] = {}
        target = url or ""

        if service:
            spec = self.services.get(service)
            if spec is None:
                known = ", ".join(sorted(self.services)) or "none configured"
                return f"Unknown service '{service}'. Available: {known}."
            base = str(spec.get("base_url", "")).rstrip("/")
            target = base + ("/" + path.lstrip("/") if path else "")
            request_headers.update({str(k): str(v) for k, v in (spec.get("headers") or {}).items()})

        if not target:
            return "Provide either a 'url' or a configured 'service'."
        request_headers.update(headers or {})

        self.policy.audit("http", f"{method} {target}")
        try:
            response = requests.request(
                method=method.upper(),
                url=target,
                params=params,
                json=json_body,
                headers=request_headers or None,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            return f"Error calling {target}: {exc}"

        body = response.text or ""
        try:
            body = json.dumps(response.json(), ensure_ascii=False, indent=2)
        except ValueError:
            pass
        if len(body) > _MAX_BODY:
            body = body[:_MAX_BODY] + f"\n...[truncated at {_MAX_BODY} chars]"
        return f"HTTP {response.status_code} {response.reason}\n\n{body}"


class ListIntegrationsTool(Tool):
    name = "list_integrations"
    description = "List the external services configured for http_request."
    parameters = {"type": "object", "properties": {}}

    def __init__(self, services: dict[str, dict[str, Any]] | None = None):
        self.services = services or {}

    def run(self) -> str:
        if not self.services:
            return "No integrations configured. Add them under 'integrations:' in config.yaml."
        lines = []
        for name, spec in sorted(self.services.items()):
            description = spec.get("description", "")
            lines.append(f"- {name}: {spec.get('base_url', '')} {description}".rstrip())
        return "\n".join(lines)


class ClipboardTool(Tool):
    name = "clipboard"
    description = (
        "Read the system clipboard, copy text into it, or look through what was copied "
        "earlier. Use action='history' to recover something that has since been overwritten."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "history", "clear_history"],
                "default": "get",
            },
            "text": {"type": "string", "description": "Text to copy when action is 'set'."},
            "limit": {
                "type": "integer",
                "description": "How many history items to show (default 10).",
                "default": 10,
            },
        },
    }

    def __init__(self, history: ClipboardHistory | None = None):
        self.history = history or ClipboardHistory()

    def run(self, action: str = "get", text: str = "", limit: int = 10) -> str:
        if action == "history":
            return self.history.format(limit)
        if action == "clear_history":
            return f"Forgot {self.history.clear()} clipboard items."

        try:
            if action == "set":
                write_clipboard(text)
                self.history.record(text)
                return f"Copied {len(text)} characters to the clipboard."
            current = read_clipboard()
        except ClipboardUnavailable as exc:
            return f"Clipboard error: {exc}"

        # Reading is also a chance to remember, so history works without the daemon.
        self.history.record(current)
        return current or "(clipboard is empty)"


class NotifyTool(Tool):
    name = "notify"
    description = (
        "Show a desktop notification to the user. On Windows this is a real toast and may "
        "carry buttons: pass action_label plus action_uri to add one."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Notification title.", "default": "Jarvis"},
            "message": {"type": "string", "description": "Notification body."},
            "action_label": {"type": "string", "description": "Optional button caption."},
            "action_uri": {
                "type": "string",
                "description": "What the button opens: a URL, or a file:// path.",
            },
        },
        "required": ["message"],
    }

    def run(
        self,
        message: str,
        title: str = "Jarvis",
        action_label: str = "",
        action_uri: str = "",
    ) -> str:
        from ..notifications import notify

        actions = [(action_label, action_uri)] if action_label and action_uri else None
        return notify(title, message, actions)
