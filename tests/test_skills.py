from pathlib import Path

from jarvis.skills import load_skills
from jarvis.tools.base import ToolRegistry

PY_SKILL = '''
from jarvis.tools.base import FunctionTool

def register(registry, config):
    registry.register(FunctionTool(
        name="greet",
        description="Say hello.",
        parameters={"type": "object", "properties": {}},
        func=lambda: "hello",
    ))
'''

YAML_SKILL = """
name: daily_report
description: Build the daily report.
prompt: |
  Summarise my notes and save the result.
"""

BROKEN_SKILL = "raise RuntimeError('boom')\n"


def test_loads_python_and_yaml_skills(tmp_path: Path):
    (tmp_path / "greet.py").write_text(PY_SKILL, encoding="utf-8")
    (tmp_path / "daily.yaml").write_text(YAML_SKILL, encoding="utf-8")

    registry = ToolRegistry()
    loaded = load_skills(registry, config=None, directories=[str(tmp_path)])

    assert "greet" in loaded
    assert "greet" in registry
    assert registry.execute("greet", {}) == "hello"
    assert "daily_report" in registry
    assert "Summarise my notes" in registry.execute("daily_report", {})


def test_broken_skill_does_not_break_startup(tmp_path: Path):
    (tmp_path / "bad.py").write_text(BROKEN_SKILL, encoding="utf-8")
    registry = ToolRegistry()
    assert load_skills(registry, config=None, directories=[str(tmp_path)]) == []


def test_missing_directory_is_ignored():
    registry = ToolRegistry()
    assert load_skills(registry, config=None, directories=["/no/such/dir"]) == []
