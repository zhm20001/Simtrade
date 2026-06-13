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
