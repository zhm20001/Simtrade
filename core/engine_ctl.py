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


# --- stop ---

def _terminate_pid(pid, timeout=5.0):
    """Send SIGTERM (Unix) or taskkill (Windows). Wait up to timeout for exit.
    Returns True if process exited."""
    if sys.platform == 'win32':
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/T'],
                           capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except PermissionError:
            raise RuntimeError(f'no permission to terminate PID {pid}')
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True
        time.sleep(0.1)
    return False


def stop():
    """Stop daemon. Cleans stale PID. Returns dict.
    Raises RuntimeError if no PID file."""
    pid = read_pid()
    if pid is None:
        raise RuntimeError('daemon not running (no PID file)')

    if not _pid_alive(pid):
        clear_pid()
        return {'status': 'stale_pid_cleaned', 'pid': pid}

    if not _terminate_pid(pid, timeout=5.0):
        raise RuntimeError(f'failed to terminate daemon PID {pid} within 5s — try kill -9')
    clear_pid()
    return {'status': 'stopped', 'pid': pid}


# --- status ---

def status():
    """Return dict describing daemon + cache state. Never raises."""
    pid = read_pid()
    if pid is None:
        return {'daemon': 'not_started', 'pid': None, 'cache': _read_cache_safe(), 'log_tail': _read_log_tail()}

    if not _pid_alive(pid):
        return {'daemon': 'crashed', 'pid': None, 'cache': _read_cache_safe(), 'log_tail': _read_log_tail()}

    cache_info = _read_cache_safe()
    return {'daemon': 'running', 'pid': pid, 'cache': cache_info, 'log_tail': _read_log_tail()}


def _read_cache_safe():
    """Return cache summary dict, or None if no cache."""
    cache_path = _cache_path()
    if not os.path.exists(cache_path):
        return None
    try:
        from core.cache import read_cache, age_secs
        from core.config import load_config
        data = read_cache()
        age = age_secs(data)
        cfg = load_config()
        ttl = (cfg.get('refresh_interval', 3) if data.get('trading_active', True)
               else cfg.get('refresh_interval_off_hours', 60)) * cfg.get('cache_ttl_multiplier', 2)
        return {
            'updated_at': data.get('updated_at'),
            'age_secs': int(age) if age is not None else None,
            'fresh': age is not None and age <= ttl,
            'trading_active': data.get('trading_active'),
            'quotes_count': len(data.get('quotes', {})),
        }
    except Exception as e:
        return {'error': str(e)}


def _read_log_tail(n=5):
    """Return last n lines of engine.log, or [] if missing."""
    log_path = _engine_log_path()
    if not os.path.exists(log_path):
        return []
    try:
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return [line.rstrip() for line in lines[-n:]]
    except OSError:
        return []
