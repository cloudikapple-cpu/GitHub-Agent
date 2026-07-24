"""Jarvis — an extensible desktop AI assistant.

The package is organised into three layers:

* ``jarvis.llm``   — pluggable LLM backends (OpenAI, Anthropic, local Ollama).
* ``jarvis.tools`` — capabilities the assistant can invoke (web, files, shell, desktop...).
* ``jarvis.agent`` — the reasoning loop that ties an LLM together with the tools.
"""

__version__ = "0.1.0"
