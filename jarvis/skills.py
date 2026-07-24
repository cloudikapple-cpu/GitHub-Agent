"""User-defined skills.

Drop files into ``~/.jarvis/skills/`` (or ``./skills/``) and they are loaded at
startup. Two formats are supported.

**1. Python skills** — a module that exposes either a ``register(registry, config)``
function or a module-level ``TOOLS`` list::

    from jarvis.tools.base import FunctionTool

    def register(registry, config):
        registry.register(FunctionTool(
            name="coffee",
            description="Start the coffee machine.",
            parameters={"type": "object", "properties": {}},
            func=lambda: "Brewing.",
        ))

**2. YAML prompt-macros** — a reusable instruction the model can call by name::

    name: daily_report
    description: Build the daily report from my notes.
    prompt: |
      Read ~/notes/today.md, summarise it in five bullets and save the result
      to ~/reports/report.md.

Skills are ordinary Python, so a malicious file can do anything your user
account can. Only install skills you trust.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from .tools.base import FunctionTool, Tool, ToolRegistry

try:  # optional dependency
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_PY_SUFFIXES = {".py"}
_YAML_SUFFIXES = {".yaml", ".yml"}


def _load_python_skill(path: Path, registry: ToolRegistry, config: Any) -> list[str]:
    spec = importlib.util.spec_from_file_location(f"jarvis_skill_{path.stem}", path)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    before = {tool.name for tool in registry}
    if hasattr(module, "register"):
        module.register(registry, config)
    for tool in getattr(module, "TOOLS", []) or []:
        if isinstance(tool, Tool):
            registry.register(tool)
    return sorted({tool.name for tool in registry} - before)


def _load_yaml_skill(path: Path, registry: ToolRegistry) -> list[str]:
    if yaml is None:
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(data.get("name") or path.stem)
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        return []
    description = str(data.get("description") or f"Run the '{name}' skill.")
    parameters = data.get("parameters") or {
        "type": "object",
        "properties": {
            "input": {"type": "string", "description": "Optional extra input for the skill."}
        },
    }

    def _run(**kwargs: Any) -> str:
        extra = kwargs.get("input") or ""
        try:
            # Templates may use {placeholders}; literal braces are left as-is.
            body = prompt.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            body = prompt
        return (
            f"Skill '{name}' instructions — follow them now using your tools:\n{body}"
            + (f"\n\nExtra input from the user: {extra}" if extra else "")
        )

    registry.register(
        FunctionTool(
            name=name,
            description=description,
            parameters=parameters,
            func=_run,
            category="skill",
        )
    )
    return [name]


def load_skills(
    registry: ToolRegistry,
    config: Any = None,
    directories: list[str] | None = None,
) -> list[str]:
    """Load every skill found in ``directories``. Returns the new tool names.

    A broken skill never prevents startup — it is reported and skipped.
    """

    dirs = directories if directories is not None else getattr(config, "skills_dirs", [])
    loaded: list[str] = []

    for raw_dir in dirs or []:
        directory = Path(raw_dir).expanduser()
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.name.startswith("_") or not path.is_file():
                continue
            try:
                if path.suffix in _PY_SUFFIXES:
                    loaded.extend(_load_python_skill(path, registry, config))
                elif path.suffix in _YAML_SUFFIXES:
                    loaded.extend(_load_yaml_skill(path, registry))
            except Exception as exc:  # noqa: BLE001 - a bad skill must not break startup
                print(f"[skills] failed to load {path.name}: {exc}", file=sys.stderr)

    return loaded
