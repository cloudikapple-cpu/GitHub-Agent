"""Local filesystem tools."""

from __future__ import annotations

import os
from pathlib import Path

from .base import Tool

_MAX_READ = 100_000


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read the text contents of a file on the local machine."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to read."},
        },
        "required": ["path"],
    }

    def run(self, path: str) -> str:
        p = Path(path).expanduser()
        if not p.is_file():
            return f"Error: '{path}' is not a file."
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error reading '{path}': {exc}"
        if len(data) > _MAX_READ:
            data = data[:_MAX_READ] + f"\n...[truncated at {_MAX_READ} chars]"
        return data


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create or overwrite a text file with the given content."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to write."},
            "content": {"type": "string", "description": "The full text content to write."},
            "append": {
                "type": "boolean",
                "description": "Append instead of overwriting (default false).",
                "default": False,
            },
        },
        "required": ["path", "content"],
    }

    def run(self, path: str, content: str, append: bool = False) -> str:
        p = Path(path).expanduser()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a" if append else "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as exc:
            return f"Error writing '{path}': {exc}"
        return f"{'Appended to' if append else 'Wrote'} {p} ({len(content)} chars)."


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "List the files and folders in a directory."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path (default current directory).",
                "default": ".",
            },
        },
    }

    def run(self, path: str = ".") -> str:
        p = Path(path).expanduser()
        if not p.is_dir():
            return f"Error: '{path}' is not a directory."
        entries = []
        for entry in sorted(p.iterdir()):
            marker = "/" if entry.is_dir() else ""
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            entries.append(f"{entry.name}{marker}\t{size} bytes")
        if not entries:
            return f"{p} is empty."
        return f"Contents of {p}:\n" + "\n".join(entries)
