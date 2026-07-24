"""Tests for the tool layer (no network or API keys required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.tools.base import FunctionTool, Tool, ToolRegistry
from jarvis.tools.files import ListDirectoryTool, ReadFileTool, WriteFileTool
from jarvis.tools.shell import PythonExecTool, ShellTool


def test_registry_register_and_execute():
    calls = {}

    def _echo(text: str) -> str:
        calls["text"] = text
        return f"echo: {text}"

    tool = FunctionTool(
        name="echo",
        description="echo text",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        func=_echo,
    )
    registry = ToolRegistry([tool])

    assert "echo" in registry
    assert len(registry) == 1
    assert registry.execute("echo", {"text": "hi"}) == "echo: hi"
    assert calls["text"] == "hi"


def test_registry_unknown_tool():
    registry = ToolRegistry()
    assert "unknown" in registry.execute("missing", {})


def test_registry_bad_arguments():
    tool = FunctionTool(
        name="needs_arg",
        description="",
        parameters={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
        func=lambda x: x,
    )
    registry = ToolRegistry([tool])
    result = registry.execute("needs_arg", {"y": "wrong"})
    assert result.lower().startswith("error")


def test_registry_serialises_non_string_result():
    tool = FunctionTool(
        name="numbers",
        description="",
        parameters={"type": "object", "properties": {}},
        func=lambda: [1, 2, 3],
    )
    registry = ToolRegistry([tool])
    assert registry.execute("numbers", {}) == "[1, 2, 3]"


def test_file_tools_roundtrip(tmp_path):
    target = tmp_path / "note.txt"
    write = WriteFileTool()
    read = ReadFileTool()
    listing = ListDirectoryTool()

    assert "Wrote" in write.run(path=str(target), content="hello world")
    assert read.run(path=str(target)) == "hello world"
    assert "Appended" in write.run(path=str(target), content="!", append=True)
    assert read.run(path=str(target)) == "hello world!"
    assert "note.txt" in listing.run(path=str(tmp_path))


def test_read_missing_file():
    assert "not a file" in ReadFileTool().run(path="/definitely/not/here.txt")


def test_shell_disabled():
    tool = ShellTool(allow=False)
    assert "disabled" in tool.run(command="echo hi")


def test_shell_runs_command():
    tool = ShellTool(allow=True)
    out = tool.run(command="echo hello-jarvis")
    assert "hello-jarvis" in out
    assert "exit code: 0" in out


def test_python_exec():
    out = PythonExecTool().run(code="print(6 * 7)")
    assert "42" in out


def test_tool_schema_shape():
    tool = WriteFileTool()
    schema = tool.schema()
    assert schema["name"] == "write_file"
    assert schema["parameters"]["type"] == "object"
    assert isinstance(tool, Tool)
