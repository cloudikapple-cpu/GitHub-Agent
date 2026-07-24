"""Tool registry assembly.

``build_default_registry(config)`` wires every built-in capability to the
security policy described by the config, then loads the user's own skills.
"""

from __future__ import annotations

from .apps import (
    InstallAppTool,
    KillProcessTool,
    ListInstalledAppsTool,
    ProcessListTool,
    SystemInfoTool,
    UninstallAppTool,
)
from .base import FunctionTool, Tool, ToolRegistry
from .desktop import HotkeyTool, OpenPathTool, ScreenshotTool, TypeTextTool
from .files import (
    CopyPathTool,
    DeletePathTool,
    FindFilesTool,
    ListDirectoryTool,
    MakeDirectoryTool,
    MovePathTool,
    ReadFileTool,
    WriteFileTool,
)
from .integrations import ClipboardTool, HttpRequestTool, ListIntegrationsTool, NotifyTool
from .shell import PythonExecTool, ShellTool
from .web import WebFetchTool, WebSearchTool

__all__ = [
    "Tool",
    "ToolRegistry",
    "FunctionTool",
    "build_default_registry",
]


def _tag(tools: list[Tool], category: str) -> list[Tool]:
    for tool in tools:
        tool.category = category
    return tools


def build_default_registry(config) -> ToolRegistry:
    """Create the registry with all built-in tools plus user skills."""

    policy = config.policy()
    registry = ToolRegistry()

    for tool in _tag([WebSearchTool(), WebFetchTool()], "web"):
        registry.register(tool)

    for tool in _tag(
        [
            ReadFileTool(policy),
            WriteFileTool(policy),
            ListDirectoryTool(policy),
            MakeDirectoryTool(policy),
            DeletePathTool(policy),
            MovePathTool(policy),
            CopyPathTool(policy),
            FindFilesTool(policy),
        ],
        "files",
    ):
        registry.register(tool)

    for tool in _tag(
        [ShellTool(allow=config.allow_shell, policy=policy), PythonExecTool(policy)], "system"
    ):
        registry.register(tool)

    for tool in _tag(
        [
            InstallAppTool(policy),
            UninstallAppTool(policy),
            ListInstalledAppsTool(policy),
            ProcessListTool(policy),
            KillProcessTool(policy),
            SystemInfoTool(policy),
        ],
        "apps",
    ):
        registry.register(tool)

    for tool in _tag(
        [OpenPathTool(), ScreenshotTool(), TypeTextTool(), HotkeyTool()], "desktop"
    ):
        registry.register(tool)

    for tool in _tag(
        [
            HttpRequestTool(config.integrations, policy),
            ListIntegrationsTool(config.integrations),
            ClipboardTool(),
            NotifyTool(),
        ],
        "integrations",
    ):
        registry.register(tool)

    # User skills last, so they can override a built-in tool by name.
    from ..skills import load_skills

    load_skills(registry, config)
    return registry
