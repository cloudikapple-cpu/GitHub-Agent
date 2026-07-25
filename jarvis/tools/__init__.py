"""Tool registry assembly.

``build_default_registry(config)`` wires every built-in capability to the
security policy described by the config, adds the optional subsystems
(long-term memory, scheduler, vision, delegation, MCP servers), then loads the
user's own skills.

Every optional subsystem degrades gracefully: a missing dependency, an
unreachable MCP server or a broken database disables that group of tools with a
warning instead of preventing Jarvis from starting.

The shared subsystem objects are attached to the registry so the daemon can
reuse them::

    registry = build_default_registry(config)
    registry.scheduler.start(handler)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..clipboard import ClipboardHistory
from ..journal import Journal
from ..sandbox import Sandbox
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
from .powershell import PowerShellTool
from .shell import PythonExecTool, ShellTool
from .undo import HistoryTool, UndoTool
from .web import WebFetchTool, WebSearchTool

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from ..config import Config

LOGGER = logging.getLogger(__name__)

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


def build_default_registry(
    config: Config,
    backend_factory: Callable[[str | None], Any] | None = None,
    agent_factory: Callable[[str | None], Any] | None = None,
    depth: int = 0,
) -> ToolRegistry:
    """Create the registry with all built-in tools plus user skills.

    ``backend_factory`` and ``agent_factory`` are supplied by the agent so the
    vision and delegation tools can spin up models without a circular import.
    """

    policy = config.policy()
    sandbox = Sandbox(config.execution_sandbox)
    # One journal for every destructive tool, so undo_last sees them all.
    journal = Journal()
    # One clipboard history shared by the tool and the daemon's watcher.
    clipboard = ClipboardHistory()
    registry = ToolRegistry()
    registry.knowledge = None
    registry.scheduler = None
    registry.sandbox = sandbox
    registry.journal = journal
    registry.clipboard = clipboard

    for tool in _tag([WebSearchTool(config.search), WebFetchTool(config.search)], "web"):
        registry.register(tool)

    for tool in _tag(
        [
            ReadFileTool(policy, journal),
            WriteFileTool(policy, journal),
            ListDirectoryTool(policy, journal),
            MakeDirectoryTool(policy, journal),
            DeletePathTool(policy, journal),
            MovePathTool(policy, journal),
            CopyPathTool(policy, journal),
            FindFilesTool(policy, journal),
            UndoTool(journal),
            HistoryTool(journal),
        ],
        "files",
    ):
        registry.register(tool)

    for tool in _tag(
        [
            ShellTool(allow=config.allow_shell, policy=policy, sandbox=sandbox),
            PowerShellTool(allow=config.allow_shell, policy=policy),
            PythonExecTool(policy, sandbox=sandbox),
        ],
        "system",
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

    # Desktop control is guarded by policy.allow_desktop; open_path also goes
    # through check_path/allow_shell so it cannot be used to launch binaries
    # behind the shell's back.
    for tool in _tag(
        [
            OpenPathTool(policy),
            ScreenshotTool(policy),
            TypeTextTool(policy),
            HotkeyTool(policy),
        ],
        "desktop",
    ):
        registry.register(tool)

    for tool in _tag(
        [
            HttpRequestTool(config.integrations, policy),
            ListIntegrationsTool(config.integrations),
            ClipboardTool(clipboard),
            NotifyTool(),
        ],
        "integrations",
    ):
        registry.register(tool)

    # -- long-term memory ---------------------------------------------
    if config.knowledge.enabled:
        try:
            from ..knowledge import KnowledgeBase, build_embedder
            from .knowledge_tools import build_knowledge_tools

            knowledge = KnowledgeBase(
                path=config.knowledge.path,
                embedder=build_embedder(config),
                top_k=config.knowledge.top_k,
            )
            registry.knowledge = knowledge
            for tool in build_knowledge_tools(knowledge):
                registry.register(tool)
        except Exception as exc:  # noqa: BLE001 - memory is optional
            LOGGER.warning("Long-term memory disabled: %s", exc)

    # -- reminders and scheduled tasks --------------------------------
    if config.scheduler.enabled:
        try:
            from ..scheduler import Scheduler
            from .scheduler_tools import build_scheduler_tools

            scheduler = Scheduler(
                path=config.scheduler.path, tick_seconds=config.scheduler.tick_seconds
            )
            registry.scheduler = scheduler
            for tool in build_scheduler_tools(scheduler):
                registry.register(tool)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Scheduler disabled: %s", exc)

    # -- vision --------------------------------------------------------
    if config.vision.enabled:
        if backend_factory is None:
            LOGGER.warning("Vision is enabled but no model factory was provided.")
        else:
            try:
                from .vision_tools import build_vision_tools

                provider = config.vision.provider or config.router.vision or None
                for tool in build_vision_tools(
                    lambda: backend_factory(provider), config.vision.max_width
                ):
                    registry.register(tool)
            except Exception as exc:  # noqa: BLE001 - vision needs Pillow
                LOGGER.warning("Vision tools disabled: %s", exc)

    # -- sub-agents ----------------------------------------------------
    if agent_factory is not None:
        from .delegation import DelegateTool

        registry.register(DelegateTool(agent_factory, depth=depth))

    # -- MCP servers ---------------------------------------------------
    if config.mcp_servers:
        try:
            from ..mcp import load_mcp_tools

            for tool in load_mcp_tools(config):
                registry.register(tool)
        except Exception as exc:  # noqa: BLE001 - a broken server must not block startup
            LOGGER.warning("MCP tools unavailable: %s", exc)

    # User skills last, so they can override a built-in tool by name.
    from ..skills import load_skills

    load_skills(registry, config)
    return registry
