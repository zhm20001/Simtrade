"""Local cache layer — atomic read/write of data/cache.json.

Consumers (CLI, watcher) call read_cache / get_quote / get_quotes.
Daemon calls write_atomic.
"""

import json
import os
import tempfile

from core import config as _config


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

