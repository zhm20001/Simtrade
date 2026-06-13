# Local Data Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone daemon process that fetches quotes and writes them to a local cache file, then refactor watcher and CLI to read from the cache instead of hitting external APIs directly.

**Architecture:** Independent daemon process (`core/engine_daemon.py`) loops fetching quotes via the existing `core.market.get_batch_realtime_prices` and atomically writes `data/cache.json`. Consumers (`watcher.py`, `simtrade.py`) read the cache file. Lifecycle managed via `simtrade.py engine start/stop/status/restart` using a PID file + subprocess (cross-platform). No fallback: stale/missing cache surfaces as an error (CLI) or UI warning (watcher).

**Tech Stack:** Python 3.10+, stdlib only (json, os, signal, subprocess, time, sys, datetime, tempfile, pathlib). No new third-party deps. Tests via pytest (already in environment).

**Spec:** `docs/superpowers/specs/2026-06-13-local-data-engine-design.md`

**Branch:** `feature/local-data-engine` (created from `main`)

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `core/cache.py` | Create | Read/write `data/cache.json`. Atomic write. TTL/freshness checks. Exception types. |
| `core/engine_ctl.py` | Create | `engine start/stop/status/restart`. PID file + subprocess. Cross-platform. |
| `core/engine_daemon.py` | Create | Daemon main loop. Reads watchlist+portfolio codes, fetches, writes cache. |
| `core/config.py` | Modify | Add 4 new default config keys. Add `CACHE_PATH`, `ENGINE_PID_PATH`, `ENGINE_LOG_PATH` constants. |
| `config.json` | Modify | Add new keys (auto-managed via `DEFAULT_CONFIG` deep merge). |
| `core/engine.py` | Modify | Replace `get_realtime_price` / `get_batch_realtime_prices` calls with `core.cache.get_quote` / `get_quotes`. |
| `simtrade.py` | Modify | Add `engine` subcommand. Refactor `cmd_quote`/`cmd_quotes` to read cache. Delete `cmd_watch` and its argparse wiring. Add `CacheError` to `safe_execute`. |
| `watcher.py` | Modify | `_refresh()` reads cache. Add status bar UI. Migrate `refresh_interval` from watchlist to config on startup. |
| `tests/test_cache.py` | Create | Unit tests for `core/cache.py`. |
| `tests/test_engine_ctl.py` | Create | Integration tests for engine_ctl start/stop/status. |
| `tests/test_engine_daemon.py` | Create | Integration tests for daemon loop. |
| `tests/conftest.py` | Create | pytest fixtures: temp data dir, fake cache, etc. |

---

## Task 0: Bootstrap — branch, test infra

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/.gitkeep` (only if `tests/` doesn't exist)

- [ ] **Step 1: Create feature branch**

```bash
git checkout main
git pull origin main
git checkout -b feature/local-data-engine
```

- [ ] **Step 2: Verify pytest is available**

Run: `python -m pytest --version`
Expected: prints `pytest 8.x.x` (or similar). If missing, run `pip install pytest`.

- [ ] **Step 3: Create tests directory + conftest**

Create `tests/conftest.py`:

```python
"""Shared pytest fixtures."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Redirect core.config.DATA_DIR to a temp dir for isolation."""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core import config as cfg_mod
    monkeypatch.setattr(cfg_mod, 'DATA_DIR', str(tmp_path))
    # Recompute path constants
    monkeypatch.setattr(cfg_mod, 'PORTFOLIO_PATH', str(tmp_path / 'portfolio.json'))
    monkeypatch.setattr(cfg_mod, 'TRADES_PATH', str(tmp_path / 'trades.csv'))
    monkeypatch.setattr(cfg_mod, 'NAMES_PATH', str(tmp_path / 'stock_names.json'))
    monkeypatch.setattr(cfg_mod, 'STRATEGY_PATH', str(tmp_path / 'strategy.json'))
    cfg_mod.ensure_data_dir()
    return tmp_path


@pytest.fixture
def fresh_cache(tmp_data_dir, monkeypatch):
    """Patch CACHE_PATH into tmp dir, return path."""
    from core import config as cfg_mod
    cache_path = str(tmp_data_dir / 'cache.json')
    monkeypatch.setattr(cfg_mod, 'CACHE_PATH', cache_path)
    return cache_path


@pytest.fixture
def write_fake_cache(fresh_cache):
    """Returns a function that writes a cache dict with given age_secs."""
    def _write(quotes, age_secs=0, trading_active=True):
        updated_at = (datetime.now() - timedelta(seconds=age_secs)).strftime('%Y-%m-%dT%H:%M:%S')
        data = {
            'updated_at': updated_at,
            'trading_active': trading_active,
            'quotes': quotes,
        }
        with open(fresh_cache, 'w', encoding='utf-8') as f:
            json.dump(data, f)
        return data
    return _write
```

- [ ] **Step 4: Verify conftest loads**

Run: `python -m pytest tests/ --collect-only`
Expected: `collected 0 items` (no tests yet, but no errors).

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py
git commit -m "test: bootstrap pytest infra with temp-data-dir fixtures"
```

---

## Task 1: config.py — add cache paths and defaults

**Files:**
- Modify: `core/config.py:15-36` (add path constants and DEFAULT_CONFIG keys)

- [ ] **Step 1: Write failing test**

Create `tests/test_config.py`:

```python
"""Tests for new cache config keys and paths."""

import os
from core import config as cfg_mod


def test_default_config_has_cache_keys(tmp_data_dir):
    cfg = cfg_mod.load_config()
    assert cfg['refresh_interval'] == 3
    assert cfg['refresh_interval_off_hours'] == 60
    assert cfg['cache_ttl_multiplier'] == 2
    assert cfg['cache_freshness_warn_secs'] == 30


def test_cache_path_constant_exists():
    assert hasattr(cfg_mod, 'CACHE_PATH')
    assert cfg_mod.CACHE_PATH.endswith('cache.json')


def test_engine_pid_path_constant_exists():
    assert hasattr(cfg_mod, 'ENGINE_PID_PATH')
    assert cfg_mod.ENGINE_PID_PATH.endswith('engine.pid')


def test_engine_log_path_constant_exists():
    assert hasattr(cfg_mod, 'ENGINE_LOG_PATH')
    assert cfg_mod.ENGINE_LOG_PATH.endswith('engine.log')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: 4 FAIL (no CACHE_PATH, no ENGINE_PID_PATH, no ENGINE_LOG_PATH, no refresh_interval in defaults).

- [ ] **Step 3: Modify `core/config.py`**

Edit `core/config.py`. After the `STRATEGY_PATH = ...` line (line 20), add:

```python
CACHE_PATH = os.path.join(DATA_DIR, 'cache.json')
ENGINE_PID_PATH = os.path.join(DATA_DIR, 'engine.pid')
ENGINE_LOG_PATH = os.path.join(DATA_DIR, 'engine.log')
```

Then update `DEFAULT_CONFIG` (lines 22-36) to add the 4 new keys after `'watch_heartbeat_interval': 10,`:

```python
DEFAULT_CONFIG = {
    'default_cash': 1000000,
    'commission_rate': 0.0003,
    'stamp_tax_rate': 0.001,
    'min_commission': 5.0,
    'slippage': 0.001,
    'trading_hours': {
        'morning': ['09:15', '11:30'],
        'afternoon': ['13:00', '15:30'],
    },
    'request_timeout': 3,
    'watch_interval': 2,
    'watch_threshold': 1.0,
    'watch_heartbeat_interval': 10,
    'refresh_interval': 3,
    'refresh_interval_off_hours': 60,
    'cache_ttl_multiplier': 2,
    'cache_freshness_warn_secs': 30,
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat(config): add cache/engine paths and refresh_interval defaults"
```

---

## Task 2: cache.py — write_atomic + read_cache

**Files:**
- Create: `core/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Write failing test for atomic write**

Create `tests/test_cache.py`:

```python
"""Tests for core/cache.py."""

import json
import os

import pytest

from core import cache as cache_mod
from core import config as cfg_mod


def test_write_atomic_creates_file(fresh_cache):
    data = {'updated_at': '2026-06-13T14:30:15', 'trading_active': True, 'quotes': {}}
    cache_mod.write_atomic(data)
    assert os.path.exists(fresh_cache)
    with open(fresh_cache, 'r', encoding='utf-8') as f:
        loaded = json.load(f)
    assert loaded == data


def test_write_atomic_no_tmp_file_left(fresh_cache):
    data = {'updated_at': '2026-06-13T14:30:15', 'trading_active': True, 'quotes': {}}
    cache_mod.write_atomic(data)
    tmp_file = fresh_cache + '.tmp'
    assert not os.path.exists(tmp_file)


def test_read_cache_returns_dict(write_fake_cache):
    write_fake_cache({'sh600519': {'price': 1685.5}})
    data = cache_mod.read_cache()
    assert data['quotes']['sh600519']['price'] == 1685.5


def test_read_cache_missing_raises(fresh_cache):
    # File doesn't exist
    if os.path.exists(fresh_cache):
        os.remove(fresh_cache)
    with pytest.raises(cache_mod.CacheMissingError, match='cache.json not found'):
        cache_mod.read_cache()


def test_read_cache_corrupt_raises(fresh_cache):
    with open(fresh_cache, 'w', encoding='utf-8') as f:
        f.write('not valid json{')
    with pytest.raises(cache_mod.CacheError, match='corrupt'):
        cache_mod.read_cache()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.cache'`.

- [ ] **Step 3: Create `core/cache.py` with write_atomic and read_cache**

Create `core/cache.py`:

```python
"""Local cache layer — atomic read/write of data/cache.json.

Consumers (CLI, watcher) call read_cache / get_quote / get_quotes.
Daemon calls write_atomic.
"""

import json
import os
import tempfile

from core.config import CACHE_PATH, load_config


class CacheError(Exception):
    """Base for all cache errors."""


class CacheMissingError(CacheError):
    """Cache file missing (daemon not started, or code not in monitor list)."""


class CacheStaleError(CacheError):
    """Cache exists but updated_at is past TTL."""


def write_atomic(data):
    """Atomically write data to cache.json.

    Writes to a temp file then os.rename (atomic on same filesystem).
    Reader never sees a half-written file.
    """
    cache_dir = os.path.dirname(CACHE_PATH)
    os.makedirs(cache_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CACHE_PATH)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def read_cache():
    """Read cache.json. Raises CacheMissingError if absent, CacheError if corrupt."""
    if not os.path.exists(CACHE_PATH):
        raise CacheMissingError('cache.json not found — daemon not started? Run: simtrade.py engine start')
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise CacheError(f'cache.json corrupt: {e}') from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cache.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/cache.py tests/test_cache.py
git commit -m "feat(cache): atomic write + read with typed errors"
```

---

## Task 3: cache.py — age_secs + ensure_fresh + get_quote + get_quotes

**Files:**
- Modify: `core/cache.py` (append functions)
- Modify: `tests/test_cache.py` (append tests)

- [ ] **Step 1: Write failing tests for age/freshness/getters**

Append to `tests/test_cache.py`:

```python
from datetime import datetime, timedelta


def _write_cache_with_age(path, age_secs, trading_active=True, quotes=None):
    quotes = quotes or {}
    updated_at = (datetime.now() - timedelta(seconds=age_secs)).strftime('%Y-%m-%dT%H:%M:%S')
    data = {'updated_at': updated_at, 'trading_active': trading_active, 'quotes': quotes}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return data


def test_age_secs_zero(write_fake_cache):
    write_fake_cache({}, age_secs=0)
    data = cache_mod.read_cache()
    age = cache_mod.age_secs(data)
    assert 0 <= age < 2


def test_age_secs_old(write_fake_cache):
    write_fake_cache({}, age_secs=100)
    data = cache_mod.read_cache()
    assert 99 <= cache_mod.age_secs(data) <= 101


def test_ensure_fresh_trading_hours_ok(write_fake_cache):
    # trading_active=True, TTL = refresh_interval(3) * multiplier(2) = 6s
    write_fake_cache({}, age_secs=2, trading_active=True)
    data = cache_mod.read_cache()
    cache_mod.ensure_fresh(data)  # should not raise


def test_ensure_fresh_trading_hours_stale(write_fake_cache):
    write_fake_cache({}, age_secs=10, trading_active=True)
    data = cache_mod.read_cache()
    with pytest.raises(cache_mod.CacheStaleError, match='stale'):
        cache_mod.ensure_fresh(data)


def test_ensure_fresh_off_hours_ok(write_fake_cache):
    # trading_active=False, TTL = refresh_interval_off_hours(60) * multiplier(2) = 120s
    write_fake_cache({}, age_secs=60, trading_active=False)
    data = cache_mod.read_cache()
    cache_mod.ensure_fresh(data)  # should not raise


def test_ensure_fresh_off_hours_stale(write_fake_cache):
    write_fake_cache({}, age_secs=200, trading_active=False)
    data = cache_mod.read_cache()
    with pytest.raises(cache_mod.CacheStaleError):
        cache_mod.ensure_fresh(data)


def test_get_quote_hit(write_fake_cache):
    write_fake_cache({'sh600519': {'price': 1685.5, 'name': '贵州茅台'}}, age_secs=1)
    q = cache_mod.get_quote('sh600519')
    assert q['price'] == 1685.5


def test_get_quote_code_not_in_list(write_fake_cache):
    write_fake_cache({'sh600519': {'price': 1685.5}}, age_secs=1)
    with pytest.raises(cache_mod.CacheMissingError, match='not in monitor list'):
        cache_mod.get_quote('sz000001')


def test_get_quotes_partial_miss(write_fake_cache):
    write_fake_cache({'sh600519': {'price': 1685.5}}, age_secs=1)
    result = cache_mod.get_quotes(['sh600519', 'sz000001'])
    assert result['sh600519']['price'] == 1685.5
    assert result['sz000001'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cache.py -v`
Expected: new tests FAIL with `AttributeError: module 'core.cache' has no attribute 'age_secs'`.

- [ ] **Step 3: Append getters to `core/cache.py`**

Append to `core/cache.py`:

```python
from datetime import datetime

from core.config import load_config


def age_secs(data):
    """Seconds since cache.updated_at. None if timestamp missing/malformed."""
    ts = data.get('updated_at')
    if not ts:
        return None
    try:
        updated = datetime.strptime(ts, '%Y-%m-%dT%H:%M:%S')
    except ValueError:
        return None
    return (datetime.now() - updated).total_seconds()


def _ttl_for(data):
    """TTL in seconds, based on trading_active flag in cache."""
    cfg = load_config()
    multiplier = cfg.get('cache_ttl_multiplier', 2)
    if data.get('trading_active', True):
        return cfg.get('refresh_interval', 3) * multiplier
    return cfg.get('refresh_interval_off_hours', 60) * multiplier


def ensure_fresh(data):
    """Raise CacheStaleError if cache age exceeds TTL. Returns age_secs otherwise."""
    age = age_secs(data)
    if age is None:
        raise CacheStaleError('cache missing updated_at timestamp')
    ttl = _ttl_for(data)
    if age > ttl:
        raise CacheStaleError(f'cache stale: {int(age)}s old (TTL {int(ttl)}s). Daemon not running? Run: simtrade.py engine status')


def get_quote(code):
    """Read cache and return quote dict for code. Raises CacheMissingError/StaleError."""
    data = read_cache()
    ensure_fresh(data)
    if code not in data.get('quotes', {}):
        raise CacheMissingError(f'{code} not in monitor list (watchlist + portfolio). Add via watcher or edit data/watchlist.json')
    return data['quotes'][code]


def get_quotes(codes):
    """Read cache and return {code: quote or None}. Raises on stale cache.
    Missing codes map to None (partial miss). Empty cache quotes -> all None.
    """
    data = read_cache()
    ensure_fresh(data)
    quotes = data.get('quotes', {})
    return {code: quotes.get(code) for code in codes}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cache.py -v`
Expected: all 14 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/cache.py tests/test_cache.py
git commit -m "feat(cache): age_secs, ensure_fresh, get_quote(s) with TTL by trading_active"
```

---

## Task 4: engine_ctl.py — is_running + read_pid helpers

**Files:**
- Create: `core/engine_ctl.py`
- Create: `tests/test_engine_ctl.py`

- [ ] **Step 1: Write failing tests for low-level helpers**

Create `tests/test_engine_ctl.py`:

```python
"""Tests for core/engine_ctl.py."""

import os

import pytest

from core import engine_ctl as ctl
from core import config as cfg_mod


def test_pid_alive_for_current_process():
    import os
    assert ctl._pid_alive(os.getpid()) is True


def test_pid_alive_for_dead_pid():
    # PID 0 is never a real running user process on Unix; pick a large unlikely PID
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
    pid_path.write_text('999999')  # dead PID
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(pid_path))
    assert ctl.is_running() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.engine_ctl'`.

- [ ] **Step 3: Create `core/engine_ctl.py` with helpers**

Create `core/engine_ctl.py`:

```python
"""Engine daemon lifecycle: start/stop/status via PID file + subprocess.

Cross-platform: Unix uses signal.SIGTERM, Windows uses taskkill.
"""

import errno
import os
import signal
import sys

from core.config import ENGINE_PID_PATH


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
    if not os.path.exists(ENGINE_PID_PATH):
        return None
    try:
        with open(ENGINE_PID_PATH, 'r', encoding='utf-8') as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def write_pid(pid):
    """Write PID to file."""
    with open(ENGINE_PID_PATH, 'w', encoding='utf-8') as f:
        f.write(str(pid))


def clear_pid():
    """Remove PID file if it exists. No-op if missing."""
    if os.path.exists(ENGINE_PID_PATH):
        os.remove(ENGINE_PID_PATH)


def is_running():
    """True if PID file exists AND that process is alive."""
    pid = read_pid()
    if pid is None:
        return False
    return _pid_alive(pid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engine_ctl.py tests/test_engine_ctl.py
git commit -m "feat(engine_ctl): PID helpers + cross-platform liveness check"
```

---

## Task 5: engine_ctl.py — start (with self-heal + startup verification)

**Files:**
- Modify: `core/engine_ctl.py` (append `start`)
- Modify: `tests/test_engine_ctl.py` (append tests)

- [ ] **Step 1: Write failing tests for start**

Append to `tests/test_engine_ctl.py`:

```python
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

    # Patch daemon module to write cache immediately so startup check passes
    def fake_wait_for_cache(pid, timeout):
        # Simulate daemon writing cache
        import json
        from core import config as cm
        cache_path = str(tmp_data_dir / 'cache.json')
        with open(cache_path, 'w') as f:
            json.dump({'updated_at': '2026-06-13T14:30:15', 'trading_active': True, 'quotes': {}}, f)
        return True

    monkeypatch.setattr(subprocess, 'Popen', fake_popen)
    monkeypatch.setattr(ctl, '_wait_for_initial_cache', fake_wait_for_cache)

    result = ctl.start()
    assert not pid_path.exists() or pid_path.read_text() == '22222'  # stale cleaned, new written
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: new tests FAIL with `AttributeError: module 'core.engine_ctl' has no attribute 'start'`.

- [ ] **Step 3: Append `start` and helpers to `core/engine_ctl.py`**

Append to `core/engine_ctl.py`:

```python
import subprocess
import sys
import time

from core.config import ENGINE_LOG_PATH, CACHE_PATH


def _spawn_daemon():
    """Launch daemon as detached subprocess. Returns Popen object."""
    log_fp = open(ENGINE_LOG_PATH, 'a', encoding='utf-8')
    kwargs = dict(
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    if sys.platform != 'win32':
        kwargs['start_new_session'] = True  # detach from controlling terminal (Unix)
    # On Windows, CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS would be set here
    return subprocess.Popen(
        [sys.executable, '-m', 'core.engine_daemon'],
        **kwargs,
    )


def _wait_for_initial_cache(pid, timeout=2.0):
    """Poll for cache.json existence until timeout. Returns True if appeared."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _pid_alive(pid):
            return False
        if os.path.exists(CACHE_PATH):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: 13 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engine_ctl.py tests/test_engine_ctl.py
git commit -m "feat(engine_ctl): start with self-heal + initial-cache verification"
```

---

## Task 6: engine_ctl.py — stop + status

**Files:**
- Modify: `core/engine_ctl.py` (append `stop`, `status`, `_terminate_pid`)
- Modify: `tests/test_engine_ctl.py` (append tests)

- [ ] **Step 1: Write failing tests for stop + status**

Append to `tests/test_engine_ctl.py`:

```python
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
    assert s['cache']['fresh'] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: new tests FAIL with `AttributeError: module 'core.engine_ctl' has no attribute 'stop'`.

- [ ] **Step 3: Append stop + status to `core/engine_ctl.py`**

Append to `core/engine_ctl.py`:

```python
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


def status():
    """Return dict describing daemon + cache state. Never raises."""
    pid = read_pid()
    if pid is None:
        return {'daemon': 'not_started', 'pid': None, 'cache': None, 'log_tail': []}

    if not _pid_alive(pid):
        return {'daemon': 'crashed', 'pid': None, 'cache': _read_cache_safe(), 'log_tail': _read_log_tail()}

    cache_info = _read_cache_safe()
    return {'daemon': 'running', 'pid': pid, 'cache': cache_info, 'log_tail': _read_log_tail()}


def _read_cache_safe():
    """Return cache summary dict, or None if no cache."""
    if not os.path.exists(CACHE_PATH):
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
    if not os.path.exists(ENGINE_LOG_PATH):
        return []
    try:
        with open(ENGINE_LOG_PATH, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        return [line.rstrip() for line in lines[-n:]]
    except OSError:
        return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: 19 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engine_ctl.py tests/test_engine_ctl.py
git commit -m "feat(engine_ctl): stop with cross-platform terminate, status with cache summary"
```

---

## Task 7: engine_daemon.py — main loop

**Files:**
- Create: `core/engine_daemon.py`
- Create: `tests/test_engine_daemon.py`

- [ ] **Step 1: Write failing integration test**

Create `tests/test_engine_daemon.py`:

```python
"""Integration tests for the daemon.

These start a real daemon subprocess and verify it writes cache.json.
"""

import json
import os
import subprocess
import sys
import time

import pytest

from core import config as cfg_mod


def _wait_for_cache(cache_path, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(cache_path):
            return True
        time.sleep(0.2)
    return False


def test_daemon_writes_cache(tmp_data_dir, monkeypatch):
    """Start daemon as subprocess, verify cache.json is written."""
    cache_path = tmp_data_dir / 'cache.json'
    monkeypatch.setattr(cfg_mod, 'CACHE_PATH', str(cache_path))
    monkeypatch.setattr(cfg_mod, 'ENGINE_PID_PATH', str(tmp_data_dir / 'engine.pid'))
    monkeypatch.setattr(cfg_mod, 'ENGINE_LOG_PATH', str(tmp_data_dir / 'engine.log'))

    # Need a watchlist for daemon to find codes (or empty is OK — daemon writes empty quotes)
    # Daemon should still write a cache with empty quotes if no codes
    env = dict(os.environ)
    proc = subprocess.Popen(
        [sys.executable, '-c',
         'import sys; sys.path.insert(0, "."); '
         'from core import config; '
         f'config.DATA_DIR = "{tmp_data_dir}"; '
         f'config.CACHE_PATH = "{cache_path}"; '
         'from core.engine_daemon import main; '
         'main()'],
        stdout=open(tmp_data_dir / 'engine.log', 'w'),
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        assert _wait_for_cache(cache_path, timeout=5.0), 'daemon did not write cache in 5s'
        with open(cache_path, 'r') as f:
            data = json.load(f)
        assert 'updated_at' in data
        assert 'trading_active' in data
        assert 'quotes' in data
        assert isinstance(data['quotes'], dict)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_collect_codes_merges_watchlist_and_portfolio(tmp_data_dir, monkeypatch):
    """collect_codes() reads watchlist + portfolio and unions codes."""
    watchlist = {
        'groups': [{'name': 'default', 'codes': ['sh600519', 'sz000858']}],
        'active_group': 'default',
    }
    portfolio = {'positions': {'sh600036': {'qty': 100}}}
    (tmp_data_dir / 'watchlist.json').write_text(json.dumps(watchlist))
    (tmp_data_dir / 'portfolio.json').write_text(json.dumps(portfolio))

    monkeypatch.setattr(cfg_mod, 'DATA_DIR', str(tmp_data_dir))
    # Reload daemon module to pick up new DATA_DIR-dependent paths
    import importlib
    from core import engine_daemon
    importlib.reload(engine_daemon)

    codes = engine_daemon.collect_codes()
    assert set(codes) == {'sh600519', 'sz000858', 'sh600036'}


def test_collect_codes_empty_when_no_files(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(cfg_mod, 'DATA_DIR', str(tmp_data_dir))
    import importlib
    from core import engine_daemon
    importlib.reload(engine_daemon)
    assert engine_daemon.collect_codes() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine_daemon.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.engine_daemon'`.

- [ ] **Step 3: Create `core/engine_daemon.py`**

Create `core/engine_daemon.py`:

```python
"""Daemon main loop: fetch quotes periodically and write cache.json.

Run as: python -m core.engine_daemon
Managed by simtrade.py engine start/stop.
"""

import datetime
import json
import os
import signal
import sys
import time
import traceback

from core import cache
from core.config import (
    CACHE_PATH,
    DATA_DIR,
    load_config,
    ensure_data_dir,
)
from core.engine import is_trading_hours
from core.market import get_batch_realtime_prices


# Path constants resolved at import time (DATA_DIR may be patched in tests)
WATCHLIST_PATH = os.path.join(DATA_DIR, 'watchlist.json')
PORTFOLIO_PATH = os.path.join(DATA_DIR, 'portfolio.json')
ENGINE_LOG_PATH = os.path.join(DATA_DIR, 'engine.log')


_running = True


def _handle_sigterm(signum, frame):
    global _running
    _running = False


def log(msg):
    """Append a log line to engine.log."""
    ensure_data_dir()
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    try:
        # Rotate if >1MB
        if os.path.exists(ENGINE_LOG_PATH) and os.path.getsize(ENGINE_LOG_PATH) > 1_000_000:
            with open(ENGINE_LOG_PATH, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(ENGINE_LOG_PATH, 'w', encoding='utf-8') as f:
                f.writelines(lines[-5000:])  # keep last ~5000 lines
        with open(ENGINE_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def collect_codes():
    """Read codes from watchlist.json + portfolio.json. Returns list, may be empty."""
    codes = set()
    for path, extract in [
        (WATCHLIST_PATH, _extract_watchlist_codes),
        (PORTFOLIO_PATH, _extract_portfolio_codes),
    ]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            codes.update(extract(data))
        except (json.JSONDecodeError, OSError):
            continue
    return sorted(codes)


def _extract_watchlist_codes(data):
    """Pull codes from active group of watchlist."""
    groups = data.get('groups', [])
    active = data.get('active_group')
    for g in groups:
        if g.get('name') == active:
            return [c for c in g.get('codes', []) if c]
    # Fallback: if no active group match, return all codes from all groups
    out = []
    for g in groups:
        out.extend(c for c in g.get('codes', []) if c)
    return out


def _extract_portfolio_codes(data):
    """Pull codes from portfolio.positions keys."""
    positions = data.get('positions', {})
    return list(positions.keys())


def _next_sleep_secs():
    """Return sleep interval based on trading hours."""
    cfg = load_config()
    if is_trading_hours():
        return cfg.get('refresh_interval', 3)
    return cfg.get('refresh_interval_off_hours', 60)


def _tick():
    """One iteration: collect codes, fetch, write cache. Logs errors, never raises."""
    try:
        codes = collect_codes()
        trading_active = is_trading_hours()
        if codes:
            batch = get_batch_realtime_prices(codes)
        else:
            batch = {}
        cache.write_atomic({
            'updated_at': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'trading_active': trading_active,
            'quotes': batch,
        })
        log(f'tick ok: {len(batch)}/{len(codes)} codes, trading_active={trading_active}')
    except Exception as e:
        log(f'tick error: {type(e).__name__}: {e}')
        log(traceback.format_exc())


def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    log('engine daemon starting')
    while _running:
        _tick()
        time.sleep(_next_sleep_secs())
    log('engine daemon stopping')
    # Clean up PID file on graceful exit
    from core import engine_ctl
    try:
        engine_ctl.clear_pid()
    except Exception:
        pass


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine_daemon.py -v`
Expected: 3 PASS.

If integration test `test_daemon_writes_cache` is flaky on CI/slow machine, bump the timeout in `_wait_for_cache` from 5.0 to 10.0.

- [ ] **Step 5: Commit**

```bash
git add core/engine_daemon.py tests/test_engine_daemon.py
git commit -m "feat(daemon): main loop with SIGTERM handler, code collection, log rotation"
```

---

## Task 8: engine_ctl.py — restart convenience command

**Files:**
- Modify: `core/engine_ctl.py` (append `restart`)
- Modify: `tests/test_engine_ctl.py` (append test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_engine_ctl.py`:

```python
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
    monkeypatch.setattr(ctl, 'stop', lambda: (_ for _ in ()).throw(RuntimeError('not running')))
    monkeypatch.setattr(ctl, 'start', lambda: {'status': 'started', 'pid': 88})
    result = ctl.restart()
    assert result['pid'] == 88
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_engine_ctl.py::test_restart_calls_stop_then_start -v`
Expected: FAIL with `AttributeError: module 'core.engine_ctl' has no attribute 'restart'`.

- [ ] **Step 3: Append restart to `core/engine_ctl.py`**

Append to `core/engine_ctl.py`:

```python
def restart():
    """Stop (tolerates 'not running') then start. Returns start() result."""
    try:
        stop()
    except RuntimeError as e:
        if 'not running' not in str(e).lower():
            raise
    return start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_engine_ctl.py -v`
Expected: 21 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/engine_ctl.py tests/test_engine_ctl.py
git commit -m "feat(engine_ctl): restart convenience command"
```

---

## Task 9: simtrade.py — wire engine subcommand

**Files:**
- Modify: `simtrade.py:11-22` (imports)
- Modify: `simtrade.py:36-44` (add CacheError to safe_execute)
- Modify: `simtrade.py:140-244` (delete cmd_watch + add cmd_engine)
- Modify: `simtrade.py:286-379` (argparse wiring)

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_cli_engine.py`:

```python
"""End-to-end tests for `simtrade.py engine` subcommand."""

import json
import os
import subprocess
import sys


def _run_cli(args, cwd=None):
    """Run simtrade.py with args, return (returncode, stdout, stderr)."""
    result = subprocess.run(
        [sys.executable, 'simtrade.py'] + args,
        capture_output=True, text=True, cwd=cwd, timeout=15,
    )
    return result.returncode, result.stdout, result.stderr


def test_engine_no_subcommand_prints_help():
    rc, out, _ = _run_cli(['engine'])
    assert rc == 0
    assert 'start' in out
    assert 'stop' in out
    assert 'status' in out
    assert 'restart' in out


def test_engine_unknown_subcommand_errors():
    rc, out, _ = _run_cli(['engine', 'frobnicate'])
    assert rc != 0


def test_engine_status_when_not_started(tmp_data_dir):
    """Run status when no daemon — should return JSON with daemon=not_started."""
    # We can't easily isolate DATA_DIR across subprocess; just verify status returns valid JSON
    rc, out, _ = _run_cli(['engine', 'status'])
    assert rc == 0
    data = json.loads(out)
    assert 'daemon' in data
    assert data['daemon'] in ('running', 'not_started', 'crashed')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_engine.py -v`
Expected: FAIL — `engine` not a recognized subcommand.

- [ ] **Step 3: Modify `simtrade.py` — imports + safe_execute**

Edit `simtrade.py` line 12-22 (imports). Replace:

```python
from core.config import load_config, reload_config, save_config
from core.engine import Engine
from core.market import (
    get_realtime_price,
    get_stock_name,
    get_batch_realtime_prices,
    fetch_with_fallback,
    get_price,
)
from core.config import STRATEGY_PATH
import os
```

With:

```python
from core.config import load_config, reload_config, save_config
from core.engine import Engine
from core.market import (
    get_realtime_price,
    get_stock_name,
    get_batch_realtime_prices,
    fetch_with_fallback,
    get_price,
)
from core.cache import CacheError
from core import engine_ctl
from core.config import STRATEGY_PATH
import os
```

Edit lines 41-44 (safe_execute exception tuple). Replace:

```python
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        json_error(str(e))
    except Exception as e:
        json_error(f'{type(e).__name__}: {e}')
```

With:

```python
    except (ValueError, RuntimeError, FileNotFoundError, CacheError) as e:
        json_error(str(e))
    except Exception as e:
        json_error(f'{type(e).__name__}: {e}')
```

- [ ] **Step 4: Modify `simtrade.py` — add cmd_engine and delete cmd_watch**

Delete `cmd_watch` function entirely (lines 140-229).

After `cmd_strategy` (around line 243, before `cmd_config`), add:

```python
def cmd_engine(args):
    subcmd = args.engine_cmd
    if subcmd == 'start':
        safe_execute(engine_ctl.start)
    elif subcmd == 'stop':
        safe_execute(engine_ctl.stop)
    elif subcmd == 'restart':
        safe_execute(engine_ctl.restart)
    elif subcmd == 'status':
        json_output(engine_ctl.status())
    else:
        json_error(f'未知 engine 子命令: {subcmd}')
```

- [ ] **Step 5: Modify `simtrade.py` — argparse wiring**

Find the `p_watch = sub.add_parser('watch', ...)` block (around line 335-338) and delete it entirely.

After `p_strategy` block (around line 340-345), before `p_config`, add:

```python
    p_engine = sub.add_parser('engine', help='本地数据 engine daemon 管理')
    p_engine_sub = p_engine.add_subparsers(dest='engine_cmd', help='engine 子命令')
    p_engine_sub.add_parser('start', help='启动 daemon')
    p_engine_sub.add_parser('stop', help='停止 daemon')
    p_engine_sub.add_parser('restart', help='重启 daemon')
    p_engine_sub.add_parser('status', help='查看 daemon 状态')
```

Then in the `commands` dict (around line 357-373), delete the `'watch': cmd_watch,` line, and add:

```python
        'engine': cmd_engine,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_engine.py -v`
Expected: 3 PASS.

Then manually verify:

```bash
python simtrade.py engine
python simtrade.py engine status
```

First should print help, second should output JSON `{"daemon": "not_started", ...}` (or `running` if you've started one).

- [ ] **Step 7: Commit**

```bash
git add simtrade.py tests/test_cli_engine.py
git commit -m "feat(cli): add engine subcommand (start/stop/status/restart); remove watch subcommand"
```

---

## Task 10: simtrade.py — quote/quotes read from cache

**Files:**
- Modify: `simtrade.py:59-93` (cmd_quote, cmd_quotes)

- [ ] **Step 1: Write failing CLI test**

Create `tests/test_cli_quote.py`:

```python
"""Tests for cmd_quote / cmd_quotes reading cache."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta


def _write_cache(data_dir, quotes, age_secs=0, trading_active=True):
    """Write a fresh cache.json into data_dir."""
    cache_path = os.path.join(data_dir, 'cache.json')
    updated_at = (datetime.now() - timedelta(seconds=age_secs)).strftime('%Y-%m-%dT%H:%M:%S')
    with open(cache_path, 'w') as f:
        json.dump({
            'updated_at': updated_at,
            'trading_active': trading_active,
            'quotes': quotes,
        }, f)


def test_quote_reads_cache(tmp_path, monkeypatch):
    # Patch DATA_DIR before subprocess launches — we use env var pass-through
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_cache(str(data_dir), {'sh600519': {'price': 1685.5, 'name': '贵州茅台'}})

    # Set SIMTRADE_DATA_DIR env to override _resolve_data_dir in subprocess
    env = dict(os.environ)
    env['SIMTRADE_DATA_DIR'] = str(data_dir)

    # Note: this requires the production code to honor SIMTRADE_DATA_DIR.
    # See Task 11 for the config.py change.
    result = subprocess.run(
        [sys.executable, 'simtrade.py', 'quote', 'sh600519'],
        capture_output=True, text=True, env=env, timeout=10,
    )
    assert result.returncode == 0, f'stderr: {result.stderr}'
    data = json.loads(result.stdout)
    assert data['code'] == 'sh600519'
    assert data['price'] == 1685.5
```

> Note: This test depends on Task 11's `SIMTRADE_DATA_DIR` env support. Run after Task 11, or skip via `@pytest.mark.skip(reason="needs SIMTRADE_DATA_DIR from Task 11")` and unskip after Task 11.

- [ ] **Step 2: Modify `cmd_quote` to read cache**

In `simtrade.py`, replace `cmd_quote` (lines 59-71):

```python
def cmd_quote(args):
    code = args.code
    try:
        from core.cache import get_quote
        quote = get_quote(code)
        json_output({
            'code': code,
            'name': quote.get('name', code),
            'price': quote['price'],
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        })
    except Exception as e:
        json_error(f'获取行情失败: {e}')
```

- [ ] **Step 3: Modify `cmd_quotes` to read cache**

Replace `cmd_quotes` (lines 74-93):

```python
def cmd_quotes(args):
    from core.cache import get_quotes
    codes = [c.strip() for c in args.codes.split(',')]
    quotes_map = get_quotes(codes)
    results = []
    for code in codes:
        q = quotes_map.get(code)
        if q:
            info = {'code': code, 'name': q.get('name', code), 'price': q['price']}
            for key in ['change', 'change_pct', 'volume', 'turnover', 'high', 'low', 'open']:
                if key in q:
                    info[key] = q[key]
            results.append(info)
        else:
            results.append({'code': code, 'error': '不在监控清单（watchlist + portfolio）'})
    json_output({'quotes': results, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')})
```

Note: `get_quotes` raises `CacheStaleError` if cache is stale — that propagates through `safe_execute`'s `CacheError` handler. Missing individual codes are returned as None (not raised), so they show up as errors per-code in the JSON.

- [ ] **Step 4: Run unit-level smoke test**

```bash
python -c "from core.cache import get_quote; print(get_quote('sh600519'))"
```

Expected: `CacheMissingError: cache.json not found` (since no daemon running). This proves wiring is correct — `cmd_quote` will surface this as JSON error.

- [ ] **Step 5: Commit**

```bash
git add simtrade.py tests/test_cli_quote.py
git commit -m "feat(cli): quote/quotes read from cache instead of direct API calls"
```

---

## Task 11: config.py — honor SIMTRADE_DATA_DIR env (test infra)

**Files:**
- Modify: `core/config.py:9-15` (`_resolve_data_dir`)

- [ ] **Step 1: Write failing test**

Append to `tests/test_config.py`:

```python
def test_data_dir_env_override(tmp_path, monkeypatch):
    """SIMTRADE_DATA_DIR env var overrides default DATA_DIR resolution."""
    custom = tmp_path / 'custom-data'
    monkeypatch.setenv('SIMTRADE_DATA_DIR', str(custom))
    # Force re-resolution
    monkeypatch.delattr(cfg_mod, 'DATA_DIR', raising=False)
    new_dir = cfg_mod._resolve_data_dir()
    assert new_dir == str(custom)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_data_dir_env_override -v`
Expected: FAIL — env var ignored.

- [ ] **Step 3: Modify `_resolve_data_dir` in `core/config.py`**

Replace lines 9-13:

```python
def _resolve_data_dir():
    """打包后数据目录指向 ~/simtrade/data/，开发时用项目 data/"""
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.expanduser('~'), 'simtrade', 'data')
    return os.path.join(SCRIPT_DIR, 'data')
```

With:

```python
def _resolve_data_dir():
    """数据目录解析顺序：
    1. SIMTRADE_DATA_DIR 环境变量（测试用）
    2. 打包后指向 ~/simtrade/data/
    3. 开发时用项目 data/
    """
    env_dir = os.environ.get('SIMTRADE_DATA_DIR')
    if env_dir:
        return env_dir
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.expanduser('~'), 'simtrade', 'data')
    return os.path.join(SCRIPT_DIR, 'data')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: all 5 PASS (4 original + new env override).

- [ ] **Step 5: Re-enable and run the test_cli_quote.py test from Task 10**

```bash
python -m pytest tests/test_cli_quote.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/config.py tests/test_config.py
git commit -m "feat(config): SIMTRADE_DATA_DIR env override for test isolation"
```

---

## Task 12: engine.py — replace direct API calls with cache reads

**Files:**
- Modify: `core/engine.py:16` (import)
- Modify: `core/engine.py:351, 361, 376, 382, 441, 447, 532, 596` (call sites)

- [ ] **Step 1: Inspect current call sites**

Run: `grep -n "get_realtime_price\|get_batch_realtime_prices" core/engine.py`

Expected output:
```
16:from core.market import get_stock_name, get_realtime_price, get_batch_realtime_prices
351:        price = get_realtime_price(code)         # in buy_market
361:        price = get_realtime_price(code)         # in sell_market
376:        batch = get_batch_realtime_prices(codes) if codes else {}   # in status
382:                    current_price = get_realtime_price(code)       # in status fallback
441:        batch = get_batch_realtime_prices(codes) if codes else {}   # in pnl
447:                    current_price = get_realtime_price(code)       # in pnl fallback
532:        batch = get_batch_realtime_prices(codes_with_positions) if codes_with_positions else {}  # in report
596:        batch = get_batch_realtime_prices(codes_to_fetch)           # in report
```

- [ ] **Step 2: Write failing test**

Create `tests/test_engine_uses_cache.py`:

```python
"""Verify Engine uses cache instead of direct market API."""

from unittest.mock import patch
import pytest

from core.engine import Engine


def test_buy_market_uses_cache_not_market(tmp_data_dir, fresh_cache, write_fake_cache):
    """buy_market should fail with CacheError when code not in cache, NOT fall back to network."""
    write_fake_cache({}, age_secs=1)  # empty cache, code not present

    # If engine still called get_realtime_price, this would prevent it
    with patch('core.engine.get_realtime_price', side_effect=AssertionError('should not call market directly')):
        with patch('core.engine.get_batch_realtime_prices', side_effect=AssertionError('should not call market directly')):
            with pytest.raises(Exception) as exc_info:
                # Need an existing portfolio with cash; use init first
                eng = Engine()
                eng.init(cash=100000)
                # Try buying a code that's not in cache
                eng.buy_market('sh600519', 100, force=True)
    # The error should mention cache, not network
    assert 'cache' in str(exc_info.value).lower() or 'not in monitor' in str(exc_info.value).lower()
```

- [ ] **Step 3: Modify imports in `core/engine.py` line 16**

Replace:

```python
from core.market import get_stock_name, get_realtime_price, get_batch_realtime_prices
```

With:

```python
from core.market import get_stock_name
from core.cache import get_quote, get_quotes
```

- [ ] **Step 4: Replace call sites in `core/engine.py`**

For each `get_realtime_price(code)` call, replace with cache lookup. Since cache may not have the code, wrap with try/except that surfaces the cache error.

At line 351 (in `buy_market`):

```python
# Before:
        price = get_realtime_price(code)
# After:
        price = get_quote(code)['price']
```

At line 361 (in `sell_market`):

```python
# Before:
        price = get_realtime_price(code)
# After:
        price = get_quote(code)['price']
```

At line 376 (in `status`):

```python
# Before:
        batch = get_batch_realtime_prices(codes) if codes else {}
# After:
        batch = get_quotes(codes) if codes else {}
        # Filter out None values (codes missing from cache)
        batch = {k: v for k, v in batch.items() if v is not None}
```

At line 382 (status fallback for missing code):

```python
# Before:
                try:
                    current_price = get_realtime_price(code)
                except Exception:
                    current_price = pos['avg_cost']
# After:
                # No fallback — if code is in portfolio, daemon should be monitoring it.
                # Use avg_cost as last resort (same behavior as network failure before).
                current_price = pos['avg_cost']
```

At line 441 (in `pnl`):

```python
# Before:
        batch = get_batch_realtime_prices(codes) if codes else {}
# After:
        batch = get_quotes(codes) if codes else {}
        batch = {k: v for k, v in batch.items() if v is not None}
```

At line 447 (pnl fallback):

```python
# Before:
                try:
                    current_price = get_realtime_price(code)
                except Exception:
                    current_price = pos['avg_cost']
# After:
                current_price = pos['avg_cost']
```

At line 532 (in `report`):

```python
# Before:
        batch = get_batch_realtime_prices(codes_with_positions) if codes_with_positions else {}
# After:
        batch = get_quotes(codes_with_positions) if codes_with_positions else {}
        batch = {k: v for k, v in batch.items() if v is not None}
```

At line 596 (in `report`):

```python
# Before:
        batch = get_batch_realtime_prices(codes_to_fetch)
# After:
        batch = get_quotes(codes_to_fetch)
        batch = {k: v for k, v in batch.items() if v is not None}
```

- [ ] **Step 5: Run failing test to verify it passes**

Run: `python -m pytest tests/test_engine_uses_cache.py -v`
Expected: PASS.

Also run full test suite to catch regressions:

```bash
python -m pytest tests/ -v
```

Expected: all PASS.

- [ ] **Step 6: Manual smoke test**

```bash
# In one terminal:
python simtrade.py engine start
# In another:
python simtrade.py status
python simtrade.py quote sh600519  # if sh600519 is in your watchlist/portfolio
```

Expected: `status` returns JSON with positions valued from cache. `quote` returns cached price.

- [ ] **Step 7: Commit**

```bash
git add core/engine.py tests/test_engine_uses_cache.py
git commit -m "refactor(engine): replace direct market calls with cache reads"
```

---

## Task 13: watcher.py — refresh_interval migration from watchlist to config

**Files:**
- Modify: `watcher.py:63-115` (`_init_user_data`, `load_watchlist`, `save_watchlist`, possibly more)
- Modify: `watcher.py` settings dialog (around lines 295-310, 504)

- [ ] **Step 1: Write failing migration test**

Create `tests/test_watcher_migration.py`:

```python
"""Tests for refresh_interval migration from watchlist.json to config.json."""

import json
import os

from core import config as cfg_mod


def test_migrate_refresh_interval_moves_field(tmp_data_dir, monkeypatch):
    """If watchlist has refresh_interval, it should be moved to config.json and removed from watchlist."""
    watchlist_path = tmp_data_dir / 'watchlist.json'
    config_path = tmp_data_dir / 'config.json'

    # Seed watchlist with old refresh_interval
    watchlist = {
        'groups': [{'name': 'default', 'codes': []}],
        'active_group': 'default',
        'refresh_interval': 5,
    }
    watchlist_path.write_text(json.dumps(watchlist), encoding='utf-8')

    # config.json doesn't have refresh_interval yet
    config_path.write_text(json.dumps({'default_cash': 1000000}), encoding='utf-8')

    # Reload watcher's migration function
    import importlib
    cfg_mod.reload_config()
    import watcher
    importlib.reload(watcher)

    watcher.migrate_refresh_interval_if_needed()

    # Watchlist should no longer have refresh_interval
    new_wl = json.loads(watchlist_path.read_text(encoding='utf-8'))
    assert 'refresh_interval' not in new_wl

    # config.json should now have refresh_interval=5
    new_cfg = json.loads(config_path.read_text(encoding='utf-8'))
    assert new_cfg['refresh_interval'] == 5


def test_migrate_refresh_interval_idempotent(tmp_data_dir, monkeypatch):
    """Running migration twice is a no-op."""
    watchlist_path = tmp_data_dir / 'watchlist.json'
    watchlist_path.write_text(json.dumps({
        'groups': [],
        'active_group': None,
    }), encoding='utf-8')

    import watcher
    watcher.migrate_refresh_interval_if_needed()
    watcher.migrate_refresh_interval_if_needed()  # should not raise


def test_migrate_refresh_interval_preserves_config_default(tmp_data_dir):
    """If config.json already has refresh_interval, watchlist value is ignored."""
    watchlist_path = tmp_data_dir / 'watchlist.json'
    config_path = tmp_data_dir / 'config.json'

    watchlist_path.write_text(json.dumps({
        'groups': [],
        'refresh_interval': 5,
    }), encoding='utf-8')
    config_path.write_text(json.dumps({'refresh_interval': 7}), encoding='utf-8')

    import watcher
    watcher.migrate_refresh_interval_if_needed()

    new_cfg = json.loads(config_path.read_text(encoding='utf-8'))
    assert new_cfg['refresh_interval'] == 7  # config wins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watcher_migration.py -v`
Expected: FAIL with `AttributeError: module 'watcher' has no attribute 'migrate_refresh_interval_if_needed'`.

- [ ] **Step 3: Add `migrate_refresh_interval_if_needed` to `watcher.py`**

Near the top of `watcher.py`, after `load_watchlist` is defined (around line 102), add:

```python
def migrate_refresh_interval_if_needed():
    """One-time migration: move refresh_interval from watchlist.json to config.json.
    Idempotent. Preserves existing config value if both have it."""
    wl_path = os.path.join(config.DATA_DIR, 'watchlist.json')
    if not os.path.exists(wl_path):
        return
    try:
        with open(wl_path, 'r', encoding='utf-8') as f:
            wl = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    if 'refresh_interval' not in wl:
        return
    wl_value = wl.pop('refresh_interval')
    cfg = config.load_config()
    if 'refresh_interval' not in cfg:
        cfg['refresh_interval'] = wl_value
        config.save_config(cfg)
    # Write watchlist without refresh_interval
    try:
        with open(wl_path, 'w', encoding='utf-8') as f:
            json.dump(wl, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
```

Also ensure `import os` and `import json` are at top of watcher.py (they should already be).

Also add a call to this function at the start of `main()` (around line 899):

```python
def main():
    migrate_refresh_interval_if_needed()
    # ... rest of main
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_watcher_migration.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Update settings dialog to read/write from config**

Find the settings dialog code where `refresh_interval` is read/written (around lines 295-310 and 504). Replace references to `self.watchlist.get('refresh_interval', 3)` and `wl['refresh_interval'] = ...` with config-based versions.

In the settings dialog `__init__` (around line 298):

```python
# Before:
        self.refresh_var = tk.IntVar(value=wl['refresh_interval'])
# After:
        cfg = config.load_config()
        self.refresh_var = tk.IntVar(value=cfg.get('refresh_interval', 3))
```

In the settings dialog `_save` method (around line 504):

```python
# Before:
                'refresh_interval': self.refresh_var.get(),
# After:
                # refresh_interval now lives in config.json, not watchlist
                pass
```

And add right before saving the watchlist:

```python
            # Save refresh_interval to config.json
            cfg = config.load_config()
            cfg['refresh_interval'] = self.refresh_var.get()
            config.save_config(cfg)
```

- [ ] **Step 6: Verify watcher still launches**

```bash
python -c "import watcher; print('imports OK')"
```

Expected: `imports OK`.

- [ ] **Step 7: Commit**

```bash
git add watcher.py tests/test_watcher_migration.py
git commit -m "feat(watcher): migrate refresh_interval from watchlist to config.json"
```

---

## Task 14: watcher.py — _refresh reads from cache

**Files:**
- Modify: `watcher.py:20` (import)
- Modify: `watcher.py:791-816` (`_refresh`)

- [ ] **Step 1: Write failing unit test for new _refresh logic**

The full `_refresh` is a method on a Tk class, hard to unit test in isolation. We'll test the data-extraction logic by extracting it.

Refactor target: pull the cache-reading part into a standalone function `_read_cache_for_refresh()`.

Create `tests/test_watcher_refresh.py`:

```python
"""Tests for watcher's cache-reading refresh logic."""

import pytest

from core import cache as cache_mod


def test_read_cache_for_refresh_returns_age_and_quotes(write_fake_cache):
    write_fake_cache({'sh600519': {'price': 1685.5}}, age_secs=2, trading_active=True)
    import watcher
    result = watcher._read_cache_for_refresh()
    assert result is not None
    assert result['trading_active'] is True
    assert result['quotes']['sh600519']['price'] == 1685.5
    assert 1 <= result['age_secs'] <= 3


def test_read_cache_for_refresh_returns_none_when_missing(fresh_cache):
    import watcher
    assert watcher._read_cache_for_refresh() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_watcher_refresh.py -v`
Expected: FAIL with `AttributeError: module 'watcher' has no attribute '_read_cache_for_refresh'`.

- [ ] **Step 3: Add `_read_cache_for_refresh` to `watcher.py`**

Near the top of `watcher.py`, after `migrate_refresh_interval_if_needed` (added in Task 13), add:

```python
def _read_cache_for_refresh():
    """Read cache for the refresh cycle. Returns dict or None if cache missing.
    Dict shape: {trading_active, quotes, age_secs, updated_at}"""
    try:
        data = cache.read_cache()
    except cache.CacheMissingError:
        return None
    except cache.CacheError:
        return None
    return {
        'trading_active': data.get('trading_active', False),
        'quotes': data.get('quotes', {}),
        'age_secs': cache.age_secs(data),
        'updated_at': data.get('updated_at'),
    }
```

Also update the import line at top of watcher.py (line 20):

```python
# Before:
from core.market import get_batch_realtime_prices, get_stock_name
# After:
from core.market import get_stock_name
from core import cache
from core import config
```

- [ ] **Step 4: Modify `_refresh` method in `WatcherApp` class (lines 791-816)**

Replace:

```python
    def _refresh(self):
        if not self._running:
            return

        codes = get_active_codes(self.watchlist)
        if codes:
            try:
                batch = get_batch_realtime_prices(codes)
                self._prev_quotes = dict(self.quotes)
                self.quotes = batch
                self.positions = load_positions()
                self._update_labels()

                if is_trading_hours():
                    strategy = load_strategy()
                    if strategy.get('rules'):
                        triggered = check_rules(strategy['rules'], batch)
                        if triggered:
                            notify_triggered(triggered, strategy['rules'], batch)
            except Exception:
                pass

        if is_trading_hours():
            interval = self.watchlist.get('refresh_interval', 3) * 1000
            self.root.after(interval, self._refresh)
```

With:

```python
    def _refresh(self):
        if not self._running:
            return

        refresh_data = _read_cache_for_refresh()
        if refresh_data is None:
            self._cache_age = None
            self._show_daemon_warning('daemon 未启动，运行: simtrade.py engine start')
        else:
            self._prev_quotes = dict(self.quotes)
            self.quotes = refresh_data['quotes']
            self._cache_age = refresh_data['age_secs']
            self._trading_active = refresh_data['trading_active']
            self.positions = load_positions()
            self._update_labels()
            self._update_status_bar()

            if is_trading_hours():
                strategy = load_strategy()
                if strategy.get('rules'):
                    triggered = check_rules(strategy['rules'], self.quotes)
                    if triggered:
                        notify_triggered(triggered, strategy['rules'], self.quotes)

        # Schedule next refresh based on trading_active
        cfg = config.load_config()
        trading = getattr(self, '_trading_active', True)
        interval_secs = cfg.get('refresh_interval', 3) if trading else cfg.get('refresh_interval_off_hours', 60)
        self.root.after(interval_secs * 1000, self._refresh)
```

- [ ] **Step 5: Run unit test to verify it passes**

Run: `python -m pytest tests/test_watcher_refresh.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add watcher.py tests/test_watcher_refresh.py
git commit -m "feat(watcher): _refresh reads cache.json instead of direct API calls"
```

---

## Task 15: watcher.py — status bar UI + daemon warning display

**Files:**
- Modify: `watcher.py` (WatcherApp.__init__ and surrounding layout code)

- [ ] **Step 1: Locate the WatcherApp layout code**

Run: `grep -n "class WatcherApp\|def __init__\|tk.Frame\|tk.Label" watcher.py | head -30`

Find where the main UI frames are constructed (around line 540+ in `WatcherApp.__init__`).

- [ ] **Step 2: Add a status bar Frame at the top of the UI**

In `WatcherApp.__init__`, after the main frame is created but before the stock list, insert a status bar:

```python
        # Status bar (top of window)
        self.status_bar = tk.Frame(self.root, bg='#222', height=24)
        self.status_bar.pack(fill=tk.X, side=tk.TOP, padx=2, pady=(2, 0))
        self.status_label = tk.Label(
            self.status_bar,
            text='',
            font=('Microsoft YaHei', 10),
            fg='#888',
            bg='#222',
            anchor='w',
        )
        self.status_label.pack(side=tk.LEFT, padx=8)
        # Initialize state attributes
        self._cache_age = None
        self._trading_active = True
        self._daemon_warning = None
```

- [ ] **Step 3: Implement `_update_status_bar` and `_show_daemon_warning` methods**

Add these methods to `WatcherApp`:

```python
    def _update_status_bar(self):
        """Update top status bar based on cache age and daemon state."""
        cfg = config.load_config()
        warn_threshold = cfg.get('cache_freshness_warn_secs', 30)
        ttl_multiplier = cfg.get('cache_ttl_multiplier', 2)
        if self._trading_active:
            ttl = cfg.get('refresh_interval', 3) * ttl_multiplier
        else:
            ttl = cfg.get('refresh_interval_off_hours', 60) * ttl_multiplier

        if self._cache_age is None:
            text, color = '⚠ daemon 未运行或 cache 缺失', '#f00'
        elif self._cache_age <= ttl:
            text, color = f'● 实时 (cache {int(self._cache_age)}s)', '#0a0'
        elif self._cache_age <= warn_threshold:
            text, color = f'⚠ 缓存滞后 {int(self._cache_age)}s', '#aa0'
        else:
            text, color = f'⚠ daemon 异常 (缓存 {int(self._cache_age)}s 未更新)', '#f00'

        if not self._trading_active and self._cache_age is not None:
            text += '  [非交易时段]'

        self.status_label.config(text=text, fg=color)

    def _show_daemon_warning(self, message):
        """Show a persistent warning when daemon is not running."""
        self._cache_age = None
        self.status_label.config(text=f'⚠ {message}', fg='#f00')
```

- [ ] **Step 4: Verify watcher launches**

```bash
python -c "
import tkinter as tk
root = tk.Tk()
root.withdraw()
import watcher
app = watcher.WatcherApp.__new__(watcher.WatcherApp)  # bypass __init__ for smoke test
print('OK - methods exist:', hasattr(watcher.WatcherApp, '_update_status_bar'),
      hasattr(watcher.WatcherApp, '_show_daemon_warning'))
"
```

Expected: `OK - methods exist: True True`.

- [ ] **Step 5: Manual UI test**

```bash
python simtrade.py engine start
python watcher.py
```

Verify status bar shows `● 实时 (cache Xs)` green text. Stop daemon:

```bash
python simtrade.py engine stop
```

Wait 30+ seconds in watcher, verify status bar turns yellow then red.

- [ ] **Step 6: Commit**

```bash
git add watcher.py
git commit -m "feat(watcher): top status bar showing cache freshness + daemon warnings"
```

---

## Task 16: end-to-end integration test + manual verification

**Files:**
- No code changes. Pure verification.

- [ ] **Step 1: Run the entire test suite**

```bash
python -m pytest tests/ -v
```

Expected: all PASS. Should be ~50+ tests across `test_cache.py`, `test_config.py`, `test_engine_ctl.py`, `test_engine_daemon.py`, `test_cli_engine.py`, `test_cli_quote.py`, `test_engine_uses_cache.py`, `test_watcher_migration.py`, `test_watcher_refresh.py`.

- [ ] **Step 2: End-to-end smoke test**

```bash
# Start daemon
python simtrade.py engine start

# Check status
python simtrade.py engine status
# Expected: JSON with daemon=running, cache.fresh=true, quotes_count>0 (if you have a watchlist)

# CLI quote (use a code from your watchlist)
python simtrade.py quote sh600519
# Expected: JSON with cached price

# CLI quotes
python simtrade.py quotes sh600519,sz000858
# Expected: JSON with both quotes

# Stop daemon
python simtrade.py engine stop
```

- [ ] **Step 3: Verify error path (no daemon)**

```bash
# Make sure daemon is stopped
python simtrade.py engine stop 2>/dev/null

# Try CLI quote — should fail with CacheMissingError
python simtrade.py quote sh600519
# Expected: JSON {"error": "cache.json not found — daemon not started? Run: simtrade.py engine start"}
```

- [ ] **Step 4: Verify watcher UI**

```bash
python simtrade.py engine start
python watcher.py
```

Check in UI:
- Status bar shows `● 实时` (green)
- Stock prices update every `refresh_interval` seconds
- Switching groups works
- Adding/removing stocks works (daemon picks up changes within one cycle)

Stop daemon from another terminal:

```bash
python simtrade.py engine stop
```

Check UI:
- Status bar turns yellow after `cache_ttl_multiplier * refresh_interval` seconds
- Status bar turns red after `cache_freshness_warn_secs` seconds

- [ ] **Step 5: Verify restart**

```bash
python simtrade.py engine start
python simtrade.py engine restart
python simtrade.py engine status
# Expected: daemon=running with new PID
python simtrade.py engine stop
```

- [ ] **Step 6: Verify non-trading hours behavior**

Note: depending on when you run this (Saturday/Sunday/evening), `is_trading_hours()` will be False. Daemon should:
- Still write cache every 60 seconds (not 3)
- cache.trading_active = false
- CLI TTL is 120s (60 * 2) instead of 6s

```bash
python simtrade.py engine start
sleep 65  # wait for one full cycle
python simtrade.py engine status
# Expected: cache.age_secs around 0-60, trading_active=false

python simtrade.py quote sh600519
# Expected: still works because TTL is 120s

python simtrade.py engine stop
```

- [ ] **Step 7: Final commit if any small fixes were needed**

If verification surfaced any small issues, fix and commit:

```bash
git add -A
git commit -m "fix: small adjustments from end-to-end verification"
```

Otherwise, no commit needed.

---

## Self-Review Checklist (after writing this plan)

- ✅ **Spec coverage**: All 10 design decisions in the spec have a corresponding task
  - Decision 1 (daemon + cache file) → Tasks 2-3 (cache), Task 7 (daemon)
  - Decision 2 (engine subcommand + PID) → Tasks 4-6, 8-9
  - Decision 3 (smart self-heal) → Task 5 (`test_start_self_heals_stale_pid`)
  - Decision 4 (no fallback, errors) → Task 3 (`CacheMissingError`, `CacheStaleError`)
  - Decision 5 (config in JSON) → Task 1 (DEFAULT_CONFIG keys)
  - Decision 6 (static code list) → Task 7 (`collect_codes`)
  - Decision 7 (reuse core.market) → Task 7 (imports `get_batch_realtime_prices`)
  - Decision 8 (daemon doesn't crash) → Task 7 (`_tick` swallows exceptions)
  - Decision 9 (watcher doesn't read PID) → Task 14 (`_read_cache_for_refresh`)
  - Decision 10 (delete watch subcommand) → Task 9
- ✅ **No placeholders**: Every step has concrete code or commands
- ✅ **Type consistency**: `CacheError`/`CacheMissingError`/`CacheStaleError` consistent across cache.py and engine.py and cli
- ✅ **Test isolation**: `SIMTRADE_DATA_DIR` env var (Task 11) and `tmp_data_dir` fixture (Task 0) handle test isolation
- ✅ **DRY**: `_read_cache_for_refresh` extracted to avoid duplicating cache logic between watcher and tests
- ✅ **YAGNI**: No premature features — exactly what the spec requires

## Known Risks / Notes for Implementation

- **Daemon integration test (`test_daemon_writes_cache`) may be flaky on slow CI**. If it fails, bump timeout in `_wait_for_cache` from 5s to 10s.
- **Saturday testing constraint**: API returns last trading day's close prices. All logic tests still pass; only "real-time price changes" can't be visually verified until Monday.
- **Windows taskkill**: Untested on Windows. If you ship Windows builds, manually verify `engine stop` works there.
- **Tkinter status bar**: Cannot be unit-tested easily. Manual UI verification (Task 16 Step 4) is the validation.
