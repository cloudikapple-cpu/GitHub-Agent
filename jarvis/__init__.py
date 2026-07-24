"""Jarvis — an extensible desktop AI assistant.

Layers:

* ``jarvis.llm``      — pluggable LLM backends (OpenAI-compatible, Anthropic, Ollama).
* ``jarvis.tools``    — capabilities (web, files, shell, desktop, apps, HTTP integrations).
* ``jarvis.skills``   — user-defined skills loaded from disk at startup.
* ``jarvis.security`` — path sandbox, command policy and audit log.
* ``jarvis.agent``    — the reasoning loop tying an LLM to the tools.
* ``jarvis.cli`` / ``jarvis.ui`` / ``jarvis.hotkey`` / ``jarvis.voice`` — interfaces.
"""

__version__ = "0.2.0"
