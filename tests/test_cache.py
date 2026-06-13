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


# --- age_secs / ensure_fresh / getters ---

from datetime import datetime, timedelta


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

