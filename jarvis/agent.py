"""The core agent: an LLM reasoning loop wired to a set of tools.

The loop is written once, in :meth:`Agent._run_loop`, and used twice.
:meth:`Agent.run` waits for the final answer; :meth:`Agent.stream` runs the very
same loop on a worker thread and hands text to the caller as it arrives -- tool
calls included. Before 0.6.0 streaming quietly gave up on any turn that used a
tool, which is most of them.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Callable

from .config import Config
from .llm import LLMBackend, build_backend
from .llm.base import ToolCall
from .memory import ConversationMemory
from .security import SecurityError
from .tools import ToolRegistry, build_default_registry

LOGGER = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """You are Jarvis, a capable desktop AI assistant.

You help the user accomplish real tasks on their computer. You can search the
web, read and write files, create and delete folders, write and run code, run
shell commands, install or remove applications, call external HTTP APIs, open
programs and URLs, set reminders, remember facts for later, look at the screen,
and control the keyboard/mouse when needed.

Guidelines:
- Think step by step and use tools to gather information instead of guessing.
- Prefer the least intrusive action that accomplishes the goal.
- When a task needs several steps, do them one at a time and check the results.
- After writing code, run it or its tests to verify it actually works.
- Use `recall` when the answer may depend on earlier sessions, and `remember`
  when the user shares a durable fact, preference or decision.
- Be concise. Report what you did and the outcome.
- If an action could be destructive or irreversible, explain it clearly first.
- If a tool refuses an action for security reasons, explain why instead of
  trying to work around the restriction.
"""

DRY_RUN_NOTE = """
DRY RUN MODE: do not call any tools. Instead, reply with the numbered plan of
actions you would take, naming the exact tool and arguments for each step, and
flag anything destructive.
"""

MAX_ITERATIONS_MESSAGE = "Stopped after reaching the maximum number of tool iterations."
CANCELLED_MESSAGE = "Stopped at your request."
#: Long-term notes below this similarity are noise and are not injected.
RECALL_THRESHOLD = 0.15
#: Sub-agents may not delegate deeper than this.
MAX_DELEGATION_DEPTH = 2

# Hook type: (tool_name, arguments) -> approved?
ConfirmHook = Callable[[str, dict[str, Any]], bool]
# Hook type: called with a human-readable trace line.
EventHook = Callable[[str], None]
# Hook type: called with each piece of text as the model produces it.
TextSink = Callable[[str], None]


class Cancelled(RuntimeError):
    """Raised internally when the user interrupts a run."""


@dataclass
class AgentEvent:
    """Emitted as the agent works, for UIs that want to show progress."""

    kind: str  # "tool_call" | "tool_result" | "final" | "error"
    text: str


class Agent:
    def __init__(
        self,
        backend: LLMBackend,
        tools: ToolRegistry,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_iterations: int = 12,
        require_confirmation: bool = True,
        confirm_hook: ConfirmHook | None = None,
        on_event: EventHook | None = None,
        memory: ConversationMemory | None = None,
        dry_run: bool = False,
        documents: Any | None = None,
        planner: Any | None = None,
        cache: Any | None = None,
        document_min_score: float = 0.12,
    ):
        self.backend = backend
        self.tools = tools
        self.max_iterations = max_iterations
        self.require_confirmation = require_confirmation
        self.confirm_hook = confirm_hook
        self.on_event = on_event
        self.memory = memory or ConversationMemory(system_prompt)
        self.dry_run = dry_run
        #: Shared subsystems, populated by :meth:`from_config` when enabled.
        self.knowledge = getattr(tools, "knowledge", None)
        self.scheduler = getattr(tools, "scheduler", None)
        #: Local document index (RAG), when configured.
        self.documents = documents
        self.document_min_score = document_min_score
        #: Cheap planning model, when configured.
        self.planner = planner
        #: Reply cache, kept for reporting and clearing.
        self.cache = cache
        #: Set by :meth:`cancel` to stop a run between steps.
        self.cancel_event = threading.Event()

    # ------------------------------------------------------------------
    @classmethod
    def from_config(
        cls,
        config: Config,
        confirm_hook: ConfirmHook | None = None,
        on_event: EventHook | None = None,
        provider: str | None = None,
        depth: int = 0,
        persist_memory: bool = True,
    ) -> Agent:
        backend = build_backend(config, provider)

        def backend_factory(name: str | None = None) -> LLMBackend:
            return build_backend(config, name)

        def agent_factory(name: str | None = None) -> Agent:
            """Helper agent for the `delegate` tool: no history, no persistence."""

            return cls.from_config(
                config,
                confirm_hook=confirm_hook,
                on_event=on_event,
                provider=name,
                depth=depth + 1,
                persist_memory=False,
            )

        tools = build_default_registry(
            config,
            backend_factory=backend_factory,
            agent_factory=agent_factory if depth < MAX_DELEGATION_DEPTH else None,
            depth=depth,
        )

        cache = cls._build_cache(config)
        if cache is not None:
            from .llm.caching import CachingBackend

            backend = CachingBackend(backend, cache)

        system_prompt = DEFAULT_SYSTEM_PROMPT
        if config.persona:
            system_prompt = f"{system_prompt}\n\nPersona:\n{config.persona.strip()}"
        if config.dry_run:
            system_prompt = f"{system_prompt}\n{DRY_RUN_NOTE}"

        memory = ConversationMemory(
            system_prompt,
            max_messages=config.memory.max_messages,
            max_chars=config.memory.max_chars,
            path=config.memory.path if (config.memory.persist and persist_memory) else None,
        )
        return cls(
            backend=backend,
            tools=tools,
            system_prompt=system_prompt,
            max_iterations=config.max_iterations,
            require_confirmation=config.require_confirmation,
            confirm_hook=confirm_hook,
            on_event=on_event,
            memory=memory,
            dry_run=config.dry_run,
            documents=cls._build_documents(config),
            planner=cls._build_planner(config, backend) if depth == 0 else None,
            cache=cache,
            document_min_score=getattr(config.rag, "min_score", 0.12),
        )

    # -- optional subsystems --------------------------------------------
    @staticmethod
    def _build_cache(config: Config) -> Any | None:
        settings = getattr(config, "cache", None)
        if settings is None or not settings.enabled:
            return None
        from .cache import ResponseCache

        try:
            return ResponseCache(
                path=settings.path,
                ttl=settings.ttl_seconds,
                max_entries=settings.max_entries,
            )
        except Exception as exc:  # noqa: BLE001 - a broken cache must not stop the agent
            LOGGER.warning("Reply cache disabled: %s", exc)
            return None

    @staticmethod
    def _build_documents(config: Config) -> Any | None:
        settings = getattr(config, "rag", None)
        if settings is None or not settings.enabled:
            return None
        from .knowledge import build_embedder
        from .rag import DocumentIndex

        try:
            return DocumentIndex(
                path=settings.path,
                embedder=build_embedder(config),
                chunk_size=settings.chunk_size,
                overlap=settings.overlap,
                top_k=settings.top_k,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Document retrieval disabled: %s", exc)
            return None

    @staticmethod
    def _build_planner(config: Config, backend: LLMBackend) -> Any | None:
        settings = getattr(config, "planner", None)
        if settings is None or not settings.enabled:
            return None
        from .planner import Planner

        planning_backend: LLMBackend = backend
        if settings.provider:
            try:
                planning_backend = build_backend(config, settings.provider)
            except Exception as exc:  # noqa: BLE001 - fall back to the main model
                LOGGER.warning("Planner provider unavailable (%s); using the main model", exc)
        return Planner(
            planning_backend, max_steps=settings.max_steps, min_chars=settings.min_chars
        )

    # ------------------------------------------------------------------
    def cancel(self) -> None:
        """Ask the current run to stop at the next safe point."""

        self.cancel_event.set()

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled

    def _emit(self, kind: str, text: str) -> None:
        if self.on_event:
            self.on_event(f"[{kind}] {text}")

    def _needs_confirmation(self, tool_name: str) -> bool:
        if not self.require_confirmation or self.confirm_hook is None:
            return False
        tool = self.tools.get(tool_name)
        return bool(tool and tool.requires_confirmation)

    def _run_tool_call(self, call: ToolCall) -> str:
        self._emit("tool_call", f"{call.name}({call.arguments})")
        if self.dry_run:
            return "Dry run: the action was not executed."
        if self._needs_confirmation(call.name):
            approved = self.confirm_hook(call.name, call.arguments)  # type: ignore[misc]
            if not approved:
                return "The user declined to run this action."
        try:
            result = self.tools.execute(call.name, call.arguments)
        except SecurityError as exc:
            result = f"Refused by security policy: {exc}"
        self._emit("tool_result", result[:500])
        return result

    # ------------------------------------------------------------------
    def _recall_context(self, user_message: str) -> str:
        """Pull relevant long-term notes for this message."""

        if self.knowledge is None:
            return ""
        try:
            notes = [
                note
                for note in self.knowledge.search(user_message)
                if note.score > RECALL_THRESHOLD
            ]
        except Exception:  # noqa: BLE001 - memory must never break a run
            return ""
        if not notes:
            return ""
        joined = "\n".join(f"- {note.text}" for note in notes)
        return f"Relevant notes from long-term memory:\n{joined}"

    def _document_context(self, user_message: str) -> str:
        """Pull relevant passages from the user's indexed documents."""

        if self.documents is None:
            return ""
        from .rag import format_context

        try:
            chunks = self.documents.search(user_message, min_score=self.document_min_score)
        except Exception:  # noqa: BLE001 - retrieval must never break a run
            return ""
        return format_context(chunks)

    def _plan_context(self, user_message: str) -> str:
        """Draft a plan for long requests, if a planner is configured."""

        if self.planner is None or self.dry_run:
            return ""
        try:
            plan = self.planner.context(user_message)
        except Exception:  # noqa: BLE001
            return ""
        if plan:
            self._emit("plan", plan)
        return plan

    def _prepare(self, user_message: str) -> list[dict[str, Any]] | None:
        """Record the user turn (with context) and return the tool schemas."""

        self.cancel_event.clear()
        blocks = [
            self._recall_context(user_message),
            self._document_context(user_message),
            self._plan_context(user_message),
        ]
        context = "\n\n".join(block for block in blocks if block)
        content = f"{context}\n\n{user_message}" if context else user_message
        self.memory.add({"role": "user", "content": content})
        return None if self.dry_run else self.tools.schemas()

    def _finish(self, text: str) -> str:
        self.memory.add({"role": "assistant", "content": text})
        self._emit("final", text)
        return text

    # ------------------------------------------------------------------
    def _guarded(self, sink: TextSink | None) -> TextSink | None:
        """Wrap ``sink`` so a cancelled run stops mid-answer, not after it."""

        if sink is None:
            return None

        def guarded(text: str) -> None:
            self._check_cancelled()
            if text:
                sink(text)

        return guarded

    def _respond(self, tool_schemas: list[dict[str, Any]] | None, sink: TextSink | None):
        """One model turn, streamed when both the caller and backend allow it."""

        messages = self.memory.messages()
        if sink is not None and getattr(self.backend, "supports_streaming", False):
            return self.backend.stream_response(messages, tools=tool_schemas, sink=sink)
        response = self.backend.chat(messages, tools=tool_schemas)
        if sink is not None and response.content and not response.wants_tools:
            sink(response.content)
        return response

    def _run_loop(self, user_message: str, sink: TextSink | None = None) -> str:
        """The reasoning loop shared by :meth:`run` and :meth:`stream`."""

        tool_schemas = self._prepare(user_message)
        guarded = self._guarded(sink)

        try:
            for _ in range(self.max_iterations):
                self._check_cancelled()
                response = self._respond(tool_schemas, guarded)

                if not response.wants_tools:
                    return self._finish(response.content or "")

                # Record the assistant's tool-call turn, then execute each call.
                self.memory.add(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls,
                    }
                )
                for call in response.tool_calls:
                    self._check_cancelled()
                    result = self._run_tool_call(call)
                    self.memory.add(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": result,
                        }
                    )
        except Cancelled:
            return self._finish(CANCELLED_MESSAGE)

        return self._finish(MAX_ITERATIONS_MESSAGE)

    # ------------------------------------------------------------------
    def run(self, user_message: str) -> str:
        """Process a single user message and return the assistant's final reply."""

        return self._run_loop(user_message)

    def stream(self, user_message: str) -> Iterator[str]:
        """Yield the reply as it is produced, tools and all.

        The loop runs on a worker thread and pushes text into a queue, so tool
        calls no longer end the stream: the assistant keeps talking between
        actions, and the trace of those actions goes to ``on_event``.
        """

        pipe: queue.Queue[str | None] = queue.Queue()
        outcome: dict[str, str] = {}

        def worker() -> None:
            try:
                outcome["text"] = self._run_loop(user_message, sink=pipe.put)
            except Exception as exc:  # noqa: BLE001 - reported to the caller below
                LOGGER.exception("Streaming run failed")
                outcome["error"] = str(exc)
            finally:
                pipe.put(None)

        thread = threading.Thread(target=worker, name="jarvis-agent-stream", daemon=True)
        thread.start()

        emitted = False
        while True:
            item = pipe.get()
            if item is None:
                break
            emitted = True
            yield item
        thread.join(timeout=5)

        if "error" in outcome:
            yield f"\n[error] {outcome['error']}"
            return
        text = outcome.get("text", "")
        # Control messages never pass through the sink, and a non-streaming
        # backend may have produced nothing at all.
        if text and (not emitted or text in {CANCELLED_MESSAGE, MAX_ITERATIONS_MESSAGE}):
            yield text
