"""Engine daemon lifecycle: start/stop/status via PID file + subprocess.

Cross-platform: Unix uses signal.SIGTERM, Windows uses taskkill.
"""

import errno
import os
import signal
import subprocess
import sys
import time

from core import config as _config


def _pid_path():
    """Read ENGINE_PID_PATH dynamically so test monkeypatch takes effect."""
    return _config.ENGINE_PID_PATH


def _cache_path():
    return _config.CACHE_PATH


def _engine_log_path():
    return _config.ENGINE_LOG_PATH


def _pid_alive(pid):
    """True if process pid is currently running. Cross-platform."""
    if pid <= 0:
        return False
    if sys.platform == 'win32':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but not ours — treat as alive
        return True
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        return False
    return True


def read_pid():
    """Return PID from file, or None if file missing/malformed."""
    pid_path = _pid_path()
    if not os.path.exists(pid_path):
        return None
    try:
        with open(pid_path, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def write_pid(pid):
    """Write PID to file."""
    pid_path = _pid_path()
    os.makedirs(os.path.dirname(pid_path), exist_ok=True)
    with open(pid_path, 'w', encoding='utf-8') as f:
        f.write(str(pid))


def clear_pid():
    """Remove PID file if it exists. No-op if missing."""
    pid_path = _pid_path()
    if os.path.exists(pid_path):
        os.remove(pid_path)


def is_running():
    """True if PID file exists AND that process is alive."""
    pid = read_pid()
    if pid is None:
        return False
    return _pid_alive(pid)


# --- start ---

def _spawn_daemon():
    """Launch daemon as detached subprocess. Returns Popen object."""
    log_path = _engine_log_path()
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log_fp = open(log_path, 'a', encoding='utf-8')
    kwargs = dict(
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    if sys.platform != 'win32':
        kwargs['start_new_session'] = True  # detach from controlling terminal (Unix)
    return subprocess.Popen(
        [sys.executable, '-m', 'core.engine_daemon'],
        **kwargs,
    )


def _wait_for_initial_cache(pid, timeout=2.0):
    """Poll for cache.json existence until timeout. Returns True if appeared."""
    cache_path = _cache_path()
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return False
        if os.path.exists(cache_path):
            return True
        time.sleep(0.1)
    return False


def start():
    """Start daemon. Self-heals stale PID. Returns dict with status/pid.
    Raises RuntimeError if already running or daemon fails to write cache."""
    pid = read_pid()
    if pid is not None:
        if _pid_alive(pid):
            raise RuntimeError(f'daemon already running, PID={pid}')
        # Stale PID — self-heal
        clear_pid()

    proc = _spawn_daemon()
    write_pid(proc.pid)

    if not _wait_for_initial_cache(proc.pid, timeout=2.0):
        clear_pid()
        raise RuntimeError('daemon failed to start within 2s — see data/engine.log')

    return {'status': 'started', 'pid': proc.pid}
