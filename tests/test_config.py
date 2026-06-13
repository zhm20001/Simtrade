"""Tests for new cache config keys and paths."""

import os
from core import config as cfg_mod


def test_default_config_has_cache_keys(tmp_data_dir):
    cfg_mod.reload_config()
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
