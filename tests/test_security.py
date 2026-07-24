from pathlib import Path

import pytest

from jarvis.security import SecurityError, SecurityPolicy
from jarvis.tools.files import DeletePathTool, MakeDirectoryTool, ReadFileTool, WriteFileTool
from jarvis.tools.shell import PythonExecTool, ShellTool


def test_default_policy_is_permissive(tmp_path: Path):
    policy = SecurityPolicy()
    assert policy.check_path(tmp_path / "a.txt") == (tmp_path / "a.txt").resolve()


def test_allowed_roots_block_outside_paths(tmp_path: Path):
    policy = SecurityPolicy(allowed_roots=[str(tmp_path)])
    policy.check_path(tmp_path / "inside.txt")
    with pytest.raises(SecurityError):
        policy.check_path("/etc/hosts")


def test_secret_paths_are_denied(tmp_path: Path):
    policy = SecurityPolicy()
    with pytest.raises(SecurityError):
        policy.check_path(Path.home() / ".ssh" / "id_rsa")


def test_dangerous_commands_are_refused():
    policy = SecurityPolicy()
    with pytest.raises(SecurityError):
        policy.check_command("rm -rf /")
    assert policy.check_command("echo hello") == "echo hello"


def test_shell_tool_reports_refusal():
    tool = ShellTool(allow=True)
    assert "Refused" in tool.run(command="rm -rf /")


def test_exec_kill_switch():
    policy = SecurityPolicy(allow_exec=False)
    assert "disabled" in PythonExecTool(policy).run(code="print(1)")


def test_file_tools_respect_sandbox(tmp_path: Path):
    policy = SecurityPolicy(allowed_roots=[str(tmp_path)])
    write = WriteFileTool(policy)
    read = ReadFileTool(policy)

    assert "Wrote" in write.run(path=str(tmp_path / "note.txt"), content="hi")
    assert read.run(path=str(tmp_path / "note.txt")) == "hi"
    assert "Refused" in write.run(path="/tmp/outside-sandbox.txt", content="nope")


def test_make_and_delete_directory(tmp_path: Path):
    policy = SecurityPolicy(allowed_roots=[str(tmp_path)])
    target = tmp_path / "project" / "src"

    assert "Created" in MakeDirectoryTool(policy).run(path=str(target))
    assert target.is_dir()

    (target / "main.py").write_text("print(1)", encoding="utf-8")
    delete = DeletePathTool(policy)
    assert "not empty" in delete.run(path=str(target))
    assert "Deleted" in delete.run(path=str(target), recursive=True)
    assert not target.exists()


def test_audit_log_is_written(tmp_path: Path):
    log = tmp_path / "audit.log"
    policy = SecurityPolicy(audit_log=str(log))
    policy.check_command("echo ok")
    assert log.is_file()
    assert "echo ok" in log.read_text(encoding="utf-8")
