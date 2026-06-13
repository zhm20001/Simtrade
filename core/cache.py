"""Local cache layer — atomic read/write of data/cache.json.

Consumers (CLI, watcher) call read_cache / get_quote / get_quotes.
Daemon calls write_atomic.
"""

import json
import os
import tempfile
from datetime import datetime

from core import config as _config
from core.config import load_config


class CacheError(Exception):
    """Base for all cache errors."""


class CacheMissingError(CacheError):
    """Cache file missing (daemon not started, or code not in monitor list)."""


class CacheStaleError(CacheError):
    """Cache exists but updated_at is past TTL."""


def _cache_path():
    """Read CACHE_PATH dynamically so test monkeypatches take effect."""
    return _config.CACHE_PATH


def write_atomic(data):
    """Atomically write data to cache.json.

    Writes to a temp file then os.replace (atomic on same filesystem).
    Reader never sees a half-written file.
    """
    cache_path = _cache_path()
    cache_dir = os.path.dirname(cache_path)
    os.makedirs(cache_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, cache_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def read_cache():
    """Read cache.json. Raises CacheMissingError if absent, CacheError if corrupt."""
    cache_path = _cache_path()
    if not os.path.exists(cache_path):
        raise CacheMissingError('cache.json not found — daemon not started? Run: simtrade.py engine start')
    try:
        with open(cache_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise CacheError(f'cache.json corrupt: {e}') from e


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
        raise CacheStaleError(
            f'cache stale: {int(age)}s old (TTL {int(ttl)}s). '
            f'Daemon not running? Run: simtrade.py engine status'
        )


def get_quote(code):
    """Read cache and return quote dict for code. Raises CacheMissingError/StaleError."""
    data = read_cache()
    ensure_fresh(data)
    if code not in data.get('quotes', {}):
        raise CacheMissingError(
            f'{code} not in monitor list (watchlist + portfolio). '
            f'Add via watcher or edit data/watchlist.json'
        )
    return data['quotes'][code]


def get_quotes(codes):
    """Read cache and return {code: quote or None}. Raises on stale cache.
    Missing codes map to None (partial miss). Empty cache quotes -> all None.
    """
    data = read_cache()
    ensure_fresh(data)
    quotes = data.get('quotes', {})
    return {code: quotes.get(code) for code in codes}

