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


# --- start ---

import subprocess
from unittest.mock import patch


def test_start_when_already_running_raises(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text(str(os.getpid()))  # write OUR pid so _pid_alive returns True
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    with pytest.raises(RuntimeError, match='already running'):
        ctl.start()


def test_start_self_heals_stale_pid(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text('999999')  # dead PID
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))

    started_popen = []

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid

    def fake_popen(*args, **kwargs):
        p = FakeProc(pid=22222)
        started_popen.append(p)
        return p

    def fake_wait_for_cache(pid, timeout):
        # Simulate daemon writing cache
        import json
        cache_path = str(tmp_data_dir / 'cache.json')
        with open(cache_path, 'w') as f:
            json.dump({'updated_at': '2026-06-13T14:30:15', 'trading_active': True, 'quotes': {}}, f)
        return True

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(ctl, '_wait_for_initial_cache', fake_wait_for_cache)

    result = ctl.start()
    assert pid_path.read_text() == '22222'  # stale cleaned, new written
    assert result['status'] == 'started'
    assert result['pid'] == 22222
    assert started_popen, "subprocess.Popen was called"


def test_start_when_daemon_crashes_raises(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'engine.pid'))

    class FakeProc:
        def __init__(self):
            self.pid = 33333

    def fake_popen(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(ctl, '_wait_for_initial_cache', lambda pid, timeout: False)

    with pytest.raises(RuntimeError, match='failed to start'):
        ctl.start()


# --- stop + status ---

def test_stop_when_no_pid_raises(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'nope.pid'))
    with pytest.raises(RuntimeError, match='not running'):
        ctl.stop()


def test_stop_stale_pid_cleans_and_reports(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text('999999')
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    result = ctl.stop()
    assert not pid_path.exists()
    assert 'stale' in result['status'].lower()


def test_stop_live_pid_sends_terminate(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text(str(os.getpid()))  # us
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))

    terminated = []

    def fake_terminate(pid, timeout):
        terminated.append(pid)
        return True

    monkeypatch.setattr(ctl, '_terminate_pid', fake_terminate)
    result = ctl.stop()
    assert terminated == [os.getpid()]
    assert not pid_path.exists()
    assert result['status'] == 'stopped'


def test_status_not_started(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'nope.pid'))
    s = ctl.status()
    assert s['daemon'] == 'not_started'
    assert s['pid'] is None


def test_status_crashed(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text('999999')
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    s = ctl.status()
    assert s['daemon'] == 'crashed'
    assert s['pid'] is None


def test_status_running_no_cache(tmp_data_dir, monkeypatch):
    pid_path = tmp_data_dir / 'engine.pid'
    pid_path.write_text(str(os.getpid()))
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    monkeypatch.setattr(cfg_mod, 'CACHE_PATH', str(tmp_data_dir / 'no-cache.json'))
    s = ctl.status()
    assert s['daemon'] == 'running'
    assert s['pid'] == os.getpid()
    assert s['cache'] is None


# --- restart ---

def test_restart_calls_stop_then_start(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'engine.pid'))
    calls = []
    monkeypatch.setattr(ctl, 'stop', lambda: calls.append('stop') or {'status': 'stopped'})
    monkeypatch.setattr(ctl, 'start', lambda: calls.append('start') or {'status': 'started', 'pid': 99})
    result = ctl.restart()
    assert calls == ['stop', 'start']
    assert result['status'] == 'started'
    assert result['pid'] == 99


def test_restart_tolerates_stop_not_running(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'engine.pid'))


    def raise_not_running():
        raise RuntimeError('not running')
    monkeypatch.setattr(ctl, 'stop', raise_not_running)
    monkeypatch.setattr(ctl, 'start', lambda: {'status': 'started', 'pid': 88})
    result = ctl.restart()
    assert result['pid'] == 88
