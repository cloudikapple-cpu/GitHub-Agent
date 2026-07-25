"""A browser interface for Jarvis.

One page, no build step, no framework, no extra dependency: the standard
library's HTTP server, server-sent events for the reply stream, and a single
HTML document. Start it with ``jarvis --web`` or let the daemon start it, then
open the printed URL -- from this machine, or from a phone on the same network
if you bind to ``0.0.0.0`` on purpose.

Security, briefly: the server binds to ``127.0.0.1`` by default and every API
call requires a token that is generated at startup and embedded in the printed
URL. Anything that can talk to this port can run shell commands as you, so
changing the host is a deliberate act, not a default.
"""

from __future__ import annotations

import json
import logging
import queue
import secrets as token_source
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
#: Kept short so a long session does not turn into a memory leak.
MAX_HISTORY = 200
#: SSE clients get a comment every few seconds so proxies keep the pipe open.
PING_SECONDS = 15

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Jarvis</title>
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin:0; height:100vh; display:flex; flex-direction:column;
  font-family: ui-sans-serif, system-ui, "Segoe UI", Roboto, sans-serif;
  background:#0f1115; color:#e7e9ee; }
header { display:flex; align-items:center; gap:12px; padding:12px 18px; border-bottom:1px solid #232734; }
header b { font-size:15px; letter-spacing:.02em; }
#status { margin-left:auto; font-size:13px; color:#8b93a7; }
#log { flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:12px; }
.msg { max-width:min(760px, 92%); padding:10px 14px; border-radius:12px;
  white-space:pre-wrap; overflow-wrap:anywhere; line-height:1.45; font-size:15px; }
.user { align-self:flex-end; background:#2b5cff22; border:1px solid #2b5cff55; }
.assistant { align-self:flex-start; background:#171a22; border:1px solid #232734; }
.trace { align-self:flex-start; font-size:12px; color:#8b93a7; font-family: ui-monospace, monospace; padding:2px 6px; }
.error { align-self:flex-start; background:#40161a; border:1px solid #7a2530; }
form { display:flex; gap:10px; padding:14px 18px; border-top:1px solid #232734; }
textarea { flex:1; height:54px; resize:none; padding:10px 12px; border-radius:10px;
  border:1px solid #232734; background:#12151c; color:inherit; font:inherit; }
button { padding:0 22px; border:0; border-radius:10px; background:#2b5cff; color:#fff;
  font-weight:600; cursor:pointer; }
button:disabled { opacity:.45; cursor:default; }
</style>
</head>
<body>
<header><b>Jarvis</b><span id="status">connecting...</span></header>
<div id="log"></div>
<form id="composer">
  <textarea id="input" placeholder="Ask Jarvis. Enter to send, Shift+Enter for a new line." autofocus></textarea>
  <button id="send" type="submit">Send</button>
</form>
<script>
const token = new URLSearchParams(location.search).get("token") || "";
const log = document.getElementById("log");
const statusLabel = document.getElementById("status");
const input = document.getElementById("input");
const send = document.getElementById("send");
const composer = document.getElementById("composer");
let current = null;

function bubble(kind, text) {
  const node = document.createElement("div");
  node.className = "msg " + kind;
  node.textContent = text;
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

function ready() {
  send.disabled = false;
  statusLabel.textContent = "connected";
  current = null;
}

const events = new EventSource("/events?token=" + encodeURIComponent(token));
events.onopen = () => { statusLabel.textContent = "connected"; };
events.onerror = () => { statusLabel.textContent = "disconnected"; };
events.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.kind === "chunk") {
    if (!current) { current = bubble("assistant", ""); }
    current.textContent += data.text;
    log.scrollTop = log.scrollHeight;
  } else if (data.kind === "assistant") {
    if (current) { current.textContent = data.text; } else { bubble("assistant", data.text); }
    ready();
  } else if (data.kind === "user") {
    bubble("user", data.text);
  } else if (data.kind === "trace") {
    bubble("trace", data.text);
  } else if (data.kind === "error") {
    bubble("error", data.text);
    ready();
  }
};

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) { return; }
  input.value = "";
  send.disabled = true;
  current = null;
  statusLabel.textContent = "thinking...";
  try {
    await fetch("/api/chat?token=" + encodeURIComponent(token), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message })
    });
  } catch (err) {
    bubble("error", String(err));
    ready();
  }
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});
</script>
</body>
</html>
"""


class WebServer:
    """Serve the chat page and stream the agent's replies to it."""

    def __init__(
        self,
        agent: Any,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token: str = "",
        stream: bool = True,
        attach_events: bool = True,
    ) -> None:
        self.agent = agent
        self.host = host or DEFAULT_HOST
        self.port = int(port)
        self.token = token or token_source.token_urlsafe(12)
        self.stream = stream
        self.history: list[dict[str, str]] = []
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._busy = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        if attach_events:
            self._attach_events()

    # -- events ---------------------------------------------------------
    def _attach_events(self) -> None:
        """Mirror the agent's trace into the page, keeping any existing hook."""

        previous = getattr(self.agent, "on_event", None)

        def hook(line: str) -> None:
            if previous is not None:
                previous(line)
            self.publish("trace", line)

        try:
            self.agent.on_event = hook
        except Exception:  # noqa: BLE001 - a stub agent may not accept attributes
            LOGGER.debug("Could not attach the event hook to the agent.")

    def subscribe(self) -> queue.Queue:
        listener: queue.Queue = queue.Queue()
        with self._lock:
            self._subscribers.append(listener)
        return listener

    def unsubscribe(self, listener: queue.Queue) -> None:
        with self._lock:
            if listener in self._subscribers:
                self._subscribers.remove(listener)

    def publish(self, kind: str, text: str) -> None:
        event = {"kind": kind, "text": text, "time": time.time()}
        if kind in {"user", "assistant", "error"}:
            self.history.append({"role": kind, "text": text})
            del self.history[:-MAX_HISTORY]
        with self._lock:
            listeners = list(self._subscribers)
        for listener in listeners:
            listener.put(event)

    # -- conversation ---------------------------------------------------
    @property
    def busy(self) -> bool:
        return self._busy.locked()

    def ask(self, message: str) -> str:
        """Run one request. Refuses to overlap with a request already running."""

        if not self._busy.acquire(blocking=False):
            self.publish("error", "Jarvis is still working on the previous request.")
            return ""
        try:
            self.publish("user", message)
            if self.stream and hasattr(self.agent, "stream"):
                parts: list[str] = []
                for chunk in self.agent.stream(message):
                    parts.append(chunk)
                    self.publish("chunk", chunk)
                reply = "".join(parts)
            else:
                reply = self.agent.run(message)
            self.publish("assistant", reply)
            return reply
        except Exception as exc:  # noqa: BLE001 - a failed turn must not kill the server
            LOGGER.exception("Web request failed")
            self.publish("error", str(exc))
            return ""
        finally:
            self._busy.release()

    def ask_async(self, message: str) -> None:
        threading.Thread(
            target=self.ask, args=(message,), name="jarvis-web-turn", daemon=True
        ).start()

    # -- lifecycle ------------------------------------------------------
    @property
    def url(self) -> str:
        host = "127.0.0.1" if self.host in {"", "0.0.0.0"} else self.host
        return f"http://{host}:{self.port}/?token={self.token}"

    def start(self) -> str:
        """Start serving in the background and return the URL to open."""

        handler = _make_handler(self)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.daemon_threads = True
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="jarvis-web", daemon=True
        )
        self._thread.start()
        return self.url

    def open_in_browser(self) -> bool:
        try:
            return webbrowser.open(self.url)
        except Exception:  # noqa: BLE001 - headless machines have no browser
            return False

    def stop(self) -> None:
        with self._lock:
            listeners = list(self._subscribers)
            self._subscribers.clear()
        for listener in listeners:
            listener.put(None)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


def _make_handler(server: WebServer) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one :class:`WebServer`."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "Jarvis"
        protocol_version = "HTTP/1.1"

        # Access logs belong in the log file, not in the user's terminal.
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            LOGGER.debug("web: " + format, *args)

        # -- helpers ----------------------------------------------------
        def _authorised(self, query: dict[str, list[str]]) -> bool:
            supplied = self.headers.get("X-Jarvis-Token", "") or (query.get("token") or [""])[0]
            return token_source.compare_digest(str(supplied), server.token)

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _deny(self) -> None:
            self._json({"error": "Invalid or missing token."}, status=403)

        # -- streaming --------------------------------------------------
        def _events(self) -> None:
            listener = server.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                while True:
                    try:
                        event = listener.get(timeout=PING_SECONDS)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    if event is None:
                        break
                    body = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {body}\n\n".encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                pass  # the tab was closed; nothing to report
            finally:
                server.unsubscribe(listener)

        # -- routes -----------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            route = parsed.path

            if route in {"/", "/index.html"}:
                self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if route == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
                return
            if not self._authorised(query):
                self._deny()
                return
            if route == "/events":
                self._events()
                return
            if route == "/api/health":
                self._json({"ok": True, "busy": server.busy, "messages": len(server.history)})
                return
            if route == "/api/history":
                self._json({"history": server.history})
                return
            self._json({"error": "Not found."}, status=404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if not self._authorised(query):
                self._deny()
                return
            if parsed.path != "/api/chat":
                self._json({"error": "Not found."}, status=404)
                return

            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json({"error": "Malformed JSON."}, status=400)
                return

            message = str(payload.get("message") or "").strip()
            if not message:
                self._json({"error": "Empty message."}, status=400)
                return

            # 'wait' answers in the response instead of over the event stream;
            # the page never uses it, but scripts and tests find it convenient.
            if payload.get("wait"):
                reply = server.ask(message)
                self._json({"ok": True, "reply": reply})
                return

            server.ask_async(message)
            self._json({"ok": True})

    return Handler


def serve(agent: Any, config: Any = None, open_browser: bool = False) -> WebServer:
    """Start a web server for ``agent`` using ``config.web`` when available."""

    web = getattr(config, "web", None)
    server = WebServer(
        agent,
        host=getattr(web, "host", DEFAULT_HOST),
        port=int(getattr(web, "port", DEFAULT_PORT)),
        token=str(getattr(web, "token", "") or ""),
        stream=bool(getattr(getattr(config, "interface", None), "stream", True)),
    )
    server.start()
    if open_browser or bool(getattr(web, "open_browser", False)):
        server.open_in_browser()
    return server
