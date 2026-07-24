"""Tool registry assembly.

``build_default_registry(config)`` wires every built-in capability to the
security policy described by the config, adds the optional subsystems
(long-term memory, scheduler, vision, delegation, MCP servers), then loads the
user's own skills.

The shared subsystem objects are attached to the registry so the daemon can
reuse them::

    registry = build_default_registry(config)
    registry.scheduler.start(handler)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

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
from .shell import PythonExecTool, ShellTool
from .web import WebFetchTool, WebSearchTool

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
    config,
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
    registry = ToolRegistry()
    registry.knowledge = None  # type: ignore[attr-defined]
    registry.scheduler = None  # type: ignore[attr-defined]
    registry.sandbox = sandbox  # type: ignore[attr-defined]

    for tool in _tag(
        [WebSearchTool(config.search), WebFetchTool(config.search)], "web"
    ):
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
        [
            ShellTool(allow=config.allow_shell, policy=policy, sandbox=sandbox),
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
            registry.knowledge = knowledge  # type: ignore[attr-defined]
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
            registry.scheduler = scheduler  # type: ignore[attr-defined]
            for tool in build_scheduler_tools(scheduler):
                registry.register(tool)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Scheduler disabled: %s", exc)

    # -- vision --------------------------------------------------------
    if config.vision.enabled and backend_factory is not None:
        from .vision_tools import build_vision_tools

        provider = config.vision.provider or config.router.vision or None
        for tool in build_vision_tools(
            lambda: backend_factory(provider), config.vision.max_width
        ):
            registry.register(tool)

    # -- sub-agents ----------------------------------------------------
    if agent_factory is not None:
        from .delegation import DelegateTool

        registry.register(DelegateTool(agent_factory, depth=depth))

    # -- MCP servers ---------------------------------------------------
    if config.mcp_servers:
        from ..mcp import load_mcp_tools

        for tool in load_mcp_tools(config):
            registry.register(tool)

    # User skills last, so they can override a built-in tool by name.
    from ..skills import load_skills

    load_skills(registry, config)
    return registry
