"""The PowerShell tool."""

from __future__ import annotations

import subprocess

from jarvis import windows
from jarvis.security import SecurityPolicy
from jarvis.tools.powershell import PowerShellTool


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(["powershell"], returncode, stdout, stderr)


def test_the_kill_switch_disables_it():
    tool = PowerShellTool(policy=SecurityPolicy(allow_shell=False))
    assert "disabled" in tool.run(script="Get-Date")


def test_output_is_formatted_with_the_exit_code(monkeypatch):
    monkeypatch.setattr(
        windows, "run_powershell", lambda script, timeout=60: _completed(0, "Windows 11", "")
    )
    result = PowerShellTool().run(script="Get-ComputerInfo")
    assert "exit code: 0" in result
    assert "Windows 11" in result


def test_stderr_is_reported(monkeypatch):
    monkeypatch.setattr(
        windows, "run_powershell", lambda script, timeout=60: _completed(1, "", "not recognised")
    )
    result = PowerShellTool().run(script="Get-Nonsense")
    assert "exit code: 1" in result
    assert "not recognised" in result


def test_a_timeout_is_explained(monkeypatch):
    def timeout(script, timeout=60):
        raise subprocess.TimeoutExpired(cmd="powershell", timeout=timeout)

    monkeypatch.setattr(windows, "run_powershell", timeout)
    assert "timed out" in PowerShellTool().run(script="Start-Sleep 999", timeout=5)


def test_a_missing_interpreter_is_explained(monkeypatch):
    def missing(script, timeout=60):
        raise FileNotFoundError("powershell")

    monkeypatch.setattr(windows, "run_powershell", missing)
    result = PowerShellTool().run(script="Get-Date")
    assert "JARVIS_POWERSHELL" in result


def test_the_deny_list_still_applies(monkeypatch):
    monkeypatch.setattr(windows, "run_powershell", lambda script, timeout=60: _completed())
    policy = SecurityPolicy(denied_command_patterns=[r"Remove-Item\s+C:\\"])
    result = PowerShellTool(policy=policy).run(script="Remove-Item C:\\ -Recurse")
    assert result.startswith("Refused:")
