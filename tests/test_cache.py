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
    if os.path.exists(fresh_cache):
        os.remove(fresh_cache)
    with pytest.raises(cache_mod.CacheMissingError, match='cache.json not found'):
        cache_mod.read_cache()


def test_read_cache_corrupt_raises(fresh_cache):
    with open(fresh_cache, 'w', encoding='utf-8') as f:
        f.write('not valid json{')
    with pytest.raises(cache_mod.CacheError, match='corrupt'):
        cache_mod.read_cache()
