"""Built-in tools and a helper to assemble the default tool set."""

from __future__ import annotations

from ..config import Config
from .base import FunctionTool, Tool, ToolRegistry
from .desktop import HotkeyTool, OpenPathTool, ScreenshotTool, TypeTextTool
from .files import ListDirectoryTool, ReadFileTool, WriteFileTool
from .shell import PythonExecTool, ShellTool
from .web import WebFetchTool, WebSearchTool

__all__ = [
    "Tool",
    "ToolRegistry",
    "FunctionTool",
    "build_default_registry",
]


def build_default_registry(config: Config) -> ToolRegistry:
    """Create a registry populated with the standard Jarvis tool set."""

    return ToolRegistry(
        [
            WebSearchTool(),
            WebFetchTool(),
            ReadFileTool(),
            WriteFileTool(),
            ListDirectoryTool(),
            ShellTool(allow=config.allow_shell),
            PythonExecTool(),
            OpenPathTool(),
            ScreenshotTool(),
            TypeTextTool(),
            HotkeyTool(),
        ]
    )
