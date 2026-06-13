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
from core import engine_ctl
from core.config import (
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
    """Pull codes from active group of watchlist. Falls back to all groups if active missing."""
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
        # Sleep in 0.5s increments so SIGTERM (which flips _running) is detected quickly
        remaining = _next_sleep_secs()
        while _running and remaining > 0:
            step = min(0.5, remaining)
            time.sleep(step)
            remaining -= step
    log('engine daemon stopping')
    # Clean up PID file on graceful exit
    try:
        engine_ctl.clear_pid()
    except Exception:
        pass


if __name__ == '__main__':
    main()
