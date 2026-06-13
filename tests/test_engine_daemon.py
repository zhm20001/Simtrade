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


def _wait_for_cache(cache_path, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(cache_path):
            return True
        time.sleep(0.2)
    return False


def test_daemon_writes_cache(tmp_data_dir, monkeypatch):
    """Start daemon as subprocess, verify cache.json is written."""
    cache_path = tmp_data_dir / 'cache.json'

    # Pass SIMTRADE_DATA_DIR to subprocess to redirect all data paths.
    env = dict(os.environ)
    env['SIMTRADE_DATA_DIR'] = str(tmp_data_dir)

    # NOTE: This test depends on Task 11's SIMTRADE_DATA_DIR env support.
    # Skip if env support not yet implemented.
    if not env_supports_simtrade_data_dir():
        pytest.skip('SIMTRADE_DATA_DIR not yet honored — run after Task 11')

    proc = subprocess.Popen(
        [sys.executable, '-m', 'core.engine_daemon'],
        stdout=open(tmp_data_dir / 'engine.log', 'w'),
        stderr=subprocess.STDOUT,
        env=env,
    )
    try:
        assert _wait_for_cache(cache_path, timeout=8.0), 'daemon did not write cache in 8s'
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


def env_supports_simtrade_data_dir():
    """Check if core.config._resolve_data_dir honors SIMTRADE_DATA_DIR."""
    # After Task 11, this returns True.
    try:
        # Patch via subprocess to check
        result = subprocess.run(
            [sys.executable, '-c',
             'import os, sys; sys.path.insert(0,"."); '
             'os.environ["SIMTRADE_DATA_DIR"]="/tmp/_simtrade_test_check"; '
             'from core import config; '
             'print(config._resolve_data_dir())'],
            capture_output=True, text=True, timeout=5,
        )
        return '/tmp/_simtrade_test_check' in result.stdout
    except Exception:
        return False


# --- unit-level tests for collect_codes ---

def test_collect_codes_merges_watchlist_and_portfolio(tmp_data_dir, monkeypatch):
    """collect_codes() reads watchlist + portfolio and unions codes."""
    watchlist = {
        'groups': [{'name': 'default', 'codes': ['sh600519', 'sz000858']}],
        'active_group': 'default',
    }
    portfolio = {'positions': {'sh600036': {'qty': 100}}}
    (tmp_data_dir / 'watchlist.json').write_text(json.dumps(watchlist, ensure_ascii=False))
    (tmp_data_dir / 'portfolio.json').write_text(json.dumps(portfolio, ensure_ascii=False))

    # engine_daemon module reads DATA_DIR at import; reload to pick up patched DATA_DIR
    import importlib
    from core import engine_daemon
    importlib.reload(engine_daemon)

    codes = engine_daemon.collect_codes()
    assert set(codes) == {'sh600519', 'sz000858', 'sh600036'}


def test_collect_codes_empty_when_no_files(tmp_data_dir, monkeypatch):
    import importlib
    from core import engine_daemon
    importlib.reload(engine_daemon)
    assert engine_daemon.collect_codes() == []


def test_collect_codes_only_active_group(tmp_data_dir, monkeypatch):
    """Only codes from active group should be included (plus portfolio)."""
    watchlist = {
        'groups': [
            {'name': 'default', 'codes': ['sh600519']},
            {'name': 'crypto', 'codes': ['btc', 'eth']},
        ],
        'active_group': 'default',
    }
    (tmp_data_dir / 'watchlist.json').write_text(json.dumps(watchlist, ensure_ascii=False))

    import importlib
    from core import engine_daemon
    importlib.reload(engine_daemon)

    codes = engine_daemon.collect_codes()
    assert 'sh600519' in codes
    assert 'btc' not in codes
    assert 'eth' not in codes
