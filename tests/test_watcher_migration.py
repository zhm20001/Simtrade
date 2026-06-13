"""Tests for refresh_interval migration from watchlist.json to config.json."""

import json
import os

from core import config as cfg_mod


def test_migrate_refresh_interval_moves_field(tmp_data_dir, monkeypatch):
    """If watchlist has refresh_interval, it should be moved to config.json and removed from watchlist."""
    # Patch WATCHLIST_PATH in watcher to point into tmp_data_dir
    import watcher
    watchlist_path = tmp_data_dir / 'watchlist.json'
    config_path = tmp_data_dir / 'config.json'

    # config.json path is fixed (SCRIPT_DIR/config.json), need to point load_config/save_config somewhere clean
    # Instead of fighting that, we'll just verify the watchlist change directly
    # and check that config.json was written.
    monkeypatch.setattr(watcher, 'WATCHLIST_PATH', str(watchlist_path))
    monkeypatch.setattr(cfg_mod, 'CONFIG_PATH', str(config_path))
    cfg_mod.reload_config()

    # Seed watchlist with old refresh_interval
    watchlist = {
        'groups': [{'name': 'default', 'codes': []}],
        'active_group': 'default',
        'refresh_interval': 5,
    }
    watchlist_path.write_text(json.dumps(watchlist), encoding='utf-8')

    watcher.migrate_refresh_interval_if_needed()

    # Watchlist should no longer have refresh_interval
    new_wl = json.loads(watchlist_path.read_text(encoding='utf-8'))
    assert 'refresh_interval' not in new_wl

    # config.json should now have refresh_interval=5
    new_cfg = json.loads(config_path.read_text(encoding='utf-8'))
    assert new_cfg['refresh_interval'] == 5


def test_migrate_refresh_interval_idempotent(tmp_data_dir, monkeypatch):
    """Running migration twice is a no-op."""
    import watcher
    watchlist_path = tmp_data_dir / 'watchlist.json'
    config_path = tmp_data_dir / 'config.json'
    monkeypatch.setattr(watcher, 'WATCHLIST_PATH', str(watchlist_path))
    monkeypatch.setattr(cfg_mod, 'CONFIG_PATH', str(config_path))
    cfg_mod.reload_config()

    watchlist_path.write_text(json.dumps({
        'groups': [],
        'active_group': None,
    }), encoding='utf-8')

    watcher.migrate_refresh_interval_if_needed()
    watcher.migrate_refresh_interval_if_needed()  # should not raise


def test_migrate_refresh_interval_preserves_config_default(tmp_data_dir, monkeypatch):
    """If config.json already has refresh_interval, watchlist value is ignored."""
    import watcher
    watchlist_path = tmp_data_dir / 'watchlist.json'
    config_path = tmp_data_dir / 'config.json'
    monkeypatch.setattr(watcher, 'WATCHLIST_PATH', str(watchlist_path))
    monkeypatch.setattr(cfg_mod, 'CONFIG_PATH', str(config_path))
    cfg_mod.reload_config()

    watchlist_path.write_text(json.dumps({
        'groups': [],
        'refresh_interval': 5,
    }), encoding='utf-8')
    config_path.write_text(json.dumps({'refresh_interval': 7}), encoding='utf-8')

    watcher.migrate_refresh_interval_if_needed()

    new_cfg = json.loads(config_path.read_text(encoding='utf-8'))
    assert new_cfg['refresh_interval'] == 7  # config wins
