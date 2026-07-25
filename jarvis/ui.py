"""A minimal always-available desktop window for talking to Jarvis.

Built on Tkinter (bundled with Python), so there is no extra dependency for the
GUI itself. The window shows the conversation, a text entry, a microphone
button, and a live trace of the tools the agent runs.

With ``stream=True`` the reply appears word by word instead of arriving in one
block after a long silence - the same setting the terminal uses
(``interface.stream``).

Called from the daemon when the global hotkey fires, or directly with
``jarvis --gui``.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from typing import Any

try:  # Tkinter is optional on some Linux distributions
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    TK_AVAILABLE = True
except ImportError:  # pragma: no cover
    TK_AVAILABLE = False


class AssistantWindow:
    """Chat window with text + voice input."""

    def __init__(self, agent, voice=None, title: str = "Jarvis", stream: bool = False):
        if not TK_AVAILABLE:
            raise RuntimeError(
                "Tkinter is not available. On Debian/Ubuntu install 'python3-tk'."
            )
        self.agent = agent
        self.voice = voice
        self.stream = bool(stream)
        self._events: queue.Queue[tuple[str, str]] = queue.Queue()
        self._busy = False

        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("760x560")
        self.root.minsize(520, 380)

        self.transcript = scrolledtext.ScrolledText(
            self.root, wrap="word", state="disabled", font=("Segoe UI", 11)
        )
        self.transcript.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        self.transcript.tag_config("user", foreground="#1f6feb")
        self.transcript.tag_config("assistant", foreground="#111111")
        self.transcript.tag_config("trace", foreground="#888888")
        self.transcript.tag_config("error", foreground="#c0392b")

        bar = tk.Frame(self.root)
        bar.pack(fill="x", padx=10, pady=(0, 10))

        self.entry = tk.Entry(bar, font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda _event: self.submit())

        self.send_button = tk.Button(bar, text="Send", width=8, command=self.submit)
        self.send_button.pack(side="left", padx=(8, 0))

        self.mic_button = tk.Button(bar, text="🎤", width=4, command=self.listen)
        self.mic_button.pack(side="left", padx=(6, 0))
        if self.voice is None:
            self.mic_button.configure(state="disabled")

        self.status = tk.Label(self.root, text="Ready", anchor="w", fg="#666666")
        self.status.pack(fill="x", padx=12, pady=(0, 8))

        self.root.after(100, self._drain_events)
        self.entry.focus_set()

    # ------------------------------------------------------------------
    def _append(self, text: str, tag: str = "assistant") -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", text + "\n", tag)
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def _append_delta(self, text: str) -> None:
        """Append a streamed fragment without starting a new line."""

        self.transcript.configure(state="normal")
        self.transcript.insert("end", text, "assistant")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def push_event(self, kind: str, text: str) -> None:
        """Thread-safe way for worker threads to write to the window."""

        self._events.put((kind, text))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, text = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "status":
                self.status.configure(text=text)
            elif kind == "delta":
                self._append_delta(text)
            else:
                self._append(text, kind)
        self.root.after(100, self._drain_events)

    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.send_button.configure(state=state)
        self.entry.configure(state=state)
        if self.voice is not None:
            self.mic_button.configure(state=state)

    def submit(self, text: str | None = None) -> None:
        message = (text if text is not None else self.entry.get()).strip()
        if not message or self._busy:
            return
        self.entry.delete(0, "end")
        self._append(f"You: {message}", "user")
        self._set_busy(True)
        self.push_event("status", "Thinking…")
        threading.Thread(target=self._work, args=(message,), daemon=True).start()

    def _stream_reply(self, message: str) -> str:
        """Render the answer as it is generated. Returns the full text."""

        chunks: list[str] = []
        self.push_event("delta", "Jarvis: ")
        for chunk in self.agent.stream(message):
            chunks.append(chunk)
            self.push_event("delta", chunk)
        self.push_event("delta", "\n")
        return "".join(chunks)

    def _work(self, message: str) -> None:
        try:
            if self.stream:
                reply = self._stream_reply(message)
            else:
                reply = self.agent.run(message)
                self.push_event("assistant", f"Jarvis: {reply}")
            if self.voice is not None and getattr(self.voice.config, "speak_replies", False):
                self.voice.speak(reply)
        except Exception as exc:  # noqa: BLE001 - surface errors in the UI
            self.push_event("error", f"Error: {exc}")
        finally:
            self.push_event("status", "Ready")
            self.root.after(0, lambda: self._set_busy(False))

    # ------------------------------------------------------------------
    def listen(self) -> None:
        if self.voice is None or self._busy:
            return
        self._set_busy(True)
        self.push_event("status", "Listening…")

        def _record() -> None:
            try:
                text = self.voice.listen()
            except Exception as exc:  # noqa: BLE001
                self.push_event("error", f"Voice error: {exc}")
                self.push_event("status", "Ready")
                self.root.after(0, lambda: self._set_busy(False))
                return
            self.root.after(0, lambda: self._set_busy(False))
            if text:
                self.root.after(0, lambda: self.submit(text))
            else:
                self.push_event("status", "Heard nothing")

        threading.Thread(target=_record, daemon=True).start()

    # ------------------------------------------------------------------
    def confirm(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Confirmation hook rendered as a modal dialog."""

        return bool(
            messagebox.askyesno(
                "Confirm action",
                f"Jarvis wants to run '{tool_name}' with:\n\n{arguments}\n\nAllow?",
            )
        )

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.attributes("-topmost", False)
        self.entry.focus_force()

    def run(self) -> None:
        self.root.mainloop()


def run_window(
    agent,
    voice=None,
    on_ready: Callable[[AssistantWindow], None] | None = None,
    stream: bool = False,
) -> None:
    window = AssistantWindow(agent, voice=voice, stream=stream)
    if on_ready:
        on_ready(window)
    window.run()
