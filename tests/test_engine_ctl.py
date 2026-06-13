"""Tests for core/engine_ctl.py."""

import os

import pytest

from core import engine_ctl as ctl
from core import config as cfg_mod


def test_pid_alive_for_current_process():
    import os
    assert ctl._pid_alive(os.getpid()) is True


def test_pid_alive_for_dead_pid():
    assert ctl._pid_alive(999999) is False


def test_read_pid_missing_returns_none(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'nonexistent.pid'))
    assert ctl.read_pid() is None


def test_read_pid_present(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text('12345')
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    assert ctl.read_pid() == 12345


def test_write_pid_creates_file(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    ctl.write_pid(67890)
    assert pid_path.read_text() == '67890'


def test_clear_pid_removes_file(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text('12345')
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    ctl.clear_pid()
    assert not pid_path.exists()


def test_clear_pid_when_missing_is_noop(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'nope.pid'))
    ctl.clear_pid()  # should not raise


def test_is_running_false_when_no_pid_file(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'nope.pid'))
    assert ctl.is_running() is False


def test_is_running_false_when_stale_pid(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text('999999')
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    assert ctl.is_running() is False
