"""Engine daemon lifecycle: start/stop/status via PID file + subprocess.

Cross-platform: Unix uses signal.SIGTERM, Windows uses taskkill.
"""

import errno
import os
import signal
import sys

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
