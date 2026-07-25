"""Local filesystem tools — all routed through the security policy."""

from __future__ import annotations

import fnmatch
import shutil

from ..security import SecurityError, SecurityPolicy
from .base import Tool

_MAX_READ = 100_000
_MAX_FIND_RESULTS = 300


class _FileTool(Tool):
    """Base class holding a :class:`SecurityPolicy`."""

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()


class ReadFileTool(_FileTool):
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
        try:
            p = self.policy.check_path(path)
        except SecurityError as exc:
            return f"Refused: {exc}"
        if not p.is_file():
            return f"Error: '{path}' is not a file."
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"Error reading '{path}': {exc}"
        if len(data) > _MAX_READ:
            data = data[:_MAX_READ] + f"\n...[truncated at {_MAX_READ} chars]"
        return data


class WriteFileTool(_FileTool):
    name = "write_file"
    description = (
        "Create or overwrite a text file with the given content. "
        "Parent folders are created automatically. Use this to write code."
    )
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
        try:
            p = self.policy.check_path(path, write=True)
        except SecurityError as exc:
            return f"Refused: {exc}"
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a" if append else "w", encoding="utf-8") as fh:
                fh.write(content)
        except OSError as exc:
            return f"Error writing '{path}': {exc}"
        return f"{'Appended to' if append else 'Wrote'} {p} ({len(content)} chars)."


class ListDirectoryTool(_FileTool):
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
        try:
            p = self.policy.check_path(path)
        except SecurityError as exc:
            return f"Refused: {exc}"
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


class MakeDirectoryTool(_FileTool):
    name = "make_directory"
    description = "Create a folder (including any missing parent folders)."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path to create."},
        },
        "required": ["path"],
    }

    def run(self, path: str) -> str:
        try:
            p = self.policy.check_path(path, write=True)
        except SecurityError as exc:
            return f"Refused: {exc}"
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"Error creating '{path}': {exc}"
        return f"Created directory {p}."


class DeletePathTool(_FileTool):
    name = "delete_path"
    description = (
        "Delete a file, or a folder together with its contents. "
        "This is irreversible — confirm with the user first."
    )
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File or folder to delete."},
            "recursive": {
                "type": "boolean",
                "description": "Required to delete a non-empty folder (default false).",
                "default": False,
            },
        },
        "required": ["path"],
    }

    def run(self, path: str, recursive: bool = False) -> str:
        try:
            p = self.policy.check_path(path, write=True)
        except SecurityError as exc:
            return f"Refused: {exc}"
        if p.parent == p:
            return "Refused: refusing to delete a filesystem root."
        if not p.exists():
            return f"Error: '{path}' does not exist."
        try:
            if p.is_dir():
                if any(p.iterdir()) and not recursive:
                    return f"'{p}' is not empty. Pass recursive=true to delete it."
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            return f"Error deleting '{path}': {exc}"
        return f"Deleted {p}."


class MovePathTool(_FileTool):
    name = "move_path"
    description = "Move or rename a file or folder."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Existing file or folder."},
            "destination": {"type": "string", "description": "New path."},
        },
        "required": ["source", "destination"],
    }

    def run(self, source: str, destination: str) -> str:
        try:
            src = self.policy.check_path(source, write=True)
            dst = self.policy.check_path(destination, write=True)
        except SecurityError as exc:
            return f"Refused: {exc}"
        if not src.exists():
            return f"Error: '{source}' does not exist."
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            return f"Error moving '{source}': {exc}"
        return f"Moved {src} -> {dst}."


class CopyPathTool(_FileTool):
    name = "copy_path"
    description = "Copy a file or an entire folder."
    requires_confirmation = True
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Existing file or folder."},
            "destination": {"type": "string", "description": "Where to copy it."},
        },
        "required": ["source", "destination"],
    }

    def run(self, source: str, destination: str) -> str:
        try:
            src = self.policy.check_path(source)
            dst = self.policy.check_path(destination, write=True)
        except SecurityError as exc:
            return f"Refused: {exc}"
        if not src.exists():
            return f"Error: '{source}' does not exist."
        try:
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        except OSError as exc:
            return f"Error copying '{source}': {exc}"
        return f"Copied {src} -> {dst}."


class FindFilesTool(_FileTool):
    name = "find_files"
    description = (
        "Find files by name pattern (glob, e.g. '*.py') under a directory, "
        "optionally searching their contents for a text fragment."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory to search in.", "default": "."},
            "pattern": {"type": "string", "description": "Filename glob, e.g. '*.md'.", "default": "*"},
            "contains": {"type": "string", "description": "Only return files containing this text."},
            "max_results": {"type": "integer", "description": "Result cap (default 50).", "default": 50},
        },
    }

    def run(
        self,
        path: str = ".",
        pattern: str = "*",
        contains: str | None = None,
        max_results: int = 50,
    ) -> str:
        try:
            root = self.policy.check_path(path)
        except SecurityError as exc:
            return f"Refused: {exc}"
        if not root.is_dir():
            return f"Error: '{path}' is not a directory."

        limit = min(int(max_results or 50), _MAX_FIND_RESULTS)
        hits: list[str] = []
        for candidate in root.rglob("*"):
            if len(hits) >= limit:
                break
            if not candidate.is_file():
                continue
            if not fnmatch.fnmatch(candidate.name, pattern):
                continue
            if contains:
                try:
                    text = candidate.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if contains not in text:
                    continue
            hits.append(str(candidate))

        if not hits:
            return f"No files matching '{pattern}' under {root}."
        return f"Found {len(hits)} file(s):\n" + "\n".join(hits)
