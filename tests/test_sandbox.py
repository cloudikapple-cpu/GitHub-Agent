"""Isolated execution."""

from __future__ import annotations

import shutil

import pytest

from jarvis.config import SandboxConfig
from jarvis.sandbox import Sandbox, SandboxUnavailable


def test_disabled_by_default():
    sandbox = Sandbox(SandboxConfig())
    assert sandbox.enabled is False
    assert sandbox.wrap("echo hi") == "echo hi"


def test_docker_command_is_isolated(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/docker")
    sandbox = Sandbox(SandboxConfig(mode="docker", image="python:3.12-slim"))
    argv = sandbox.wrap("python -V", cwd=None)
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "--network" in argv and "none" in argv
    assert argv[-3:] == ["sh", "-lc", "python -V"]


def test_docker_network_can_be_allowed(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/docker")
    argv = Sandbox(SandboxConfig(mode="docker", network=True)).wrap("curl example.com")
    assert "--network" not in argv


def test_missing_runtime_is_reported(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(SandboxUnavailable):
        Sandbox(SandboxConfig(mode="firejail")).wrap("ls")


def test_plain_execution_captures_output():
    result = Sandbox(SandboxConfig()).run("echo sandbox-ok")
    assert result.exit_code == 0
    assert "sandbox-ok" in result.stdout
    assert "exit code: 0" in result.format()
