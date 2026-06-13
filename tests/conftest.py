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
