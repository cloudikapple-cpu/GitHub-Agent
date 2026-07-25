"""The daemon PID lock."""

from __future__ import annotations

import os

import pytest

from jarvis.singleton import AlreadyRunning, SingleInstance, pid_alive


def test_the_lock_is_written_and_released(tmp_path):
    path = tmp_path / "daemon.lock"
    lock = SingleInstance(path).acquire()
    assert path.read_text(encoding="utf-8") == str(os.getpid())
    lock.release()
    assert not path.exists()


def test_a_second_daemon_is_refused(tmp_path, monkeypatch):
    path = tmp_path / "daemon.lock"
    path.write_text("4242", encoding="utf-8")
    monkeypatch.setattr("jarvis.singleton.pid_alive", lambda pid: True)
    with pytest.raises(AlreadyRunning):
        SingleInstance(path).acquire()


def test_a_stale_lock_is_reclaimed(tmp_path, monkeypatch):
    path = tmp_path / "daemon.lock"
    path.write_text("4242", encoding="utf-8")
    monkeypatch.setattr("jarvis.singleton.pid_alive", lambda pid: False)
    lock = SingleInstance(path).acquire()
    assert path.read_text(encoding="utf-8") == str(os.getpid())
    lock.release()


def test_a_damaged_lock_file_is_ignored(tmp_path):
    path = tmp_path / "daemon.lock"
    path.write_text("not-a-pid", encoding="utf-8")
    assert SingleInstance(path).owner() is None


def test_missing_lock_file_means_free(tmp_path):
    assert SingleInstance(tmp_path / "nothing.lock").owner() is None


def test_the_context_manager_releases_the_lock(tmp_path):
    path = tmp_path / "daemon.lock"
    with SingleInstance(path):
        assert path.exists()
    assert not path.exists()


def test_pid_liveness():
    assert pid_alive(os.getpid())
    assert not pid_alive(0)
