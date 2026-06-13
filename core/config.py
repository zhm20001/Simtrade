"""配置管理 — 深度合并、缓存、reload"""

import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _resolve_data_dir():
    """数据目录解析顺序：
    1. SIMTRADE_DATA_DIR 环境变量（测试用）
    2. 打包后指向 ~/simtrade/data/
    3. 开发时用项目 data/
    """
    env_dir = os.environ.get('SIMTRADE_DATA_DIR')
    if env_dir:
        return env_dir
    if getattr(sys, 'frozen', False):
        return os.path.join(os.path.expanduser('~'), 'simtrade', 'data')
    return os.path.join(SCRIPT_DIR, 'data')

DATA_DIR = _resolve_data_dir()
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')
PORTFOLIO_PATH = os.path.join(DATA_DIR, 'portfolio.json')
TRADES_PATH = os.path.join(DATA_DIR, 'trades.csv')
NAMES_PATH = os.path.join(DATA_DIR, 'stock_names.json')
STRATEGY_PATH = os.path.join(DATA_DIR, 'strategy.json')
CACHE_PATH = os.path.join(DATA_DIR, 'cache.json')
ENGINE_PID_PATH = os.path.join(DATA_DIR, 'engine.pid')
ENGINE_LOG_PATH = os.path.join(DATA_DIR, 'engine.log')

DEFAULT_CONFIG = {
    'default_cash': 1000000,
    'commission_rate': 0.0003,
    'stamp_tax_rate': 0.001,
    'min_commission': 5.0,
    'slippage': 0.001,
    'trading_hours': {
        'morning': ['09:15', '11:30'],
        'afternoon': ['13:00', '15:30'],
    },
    'request_timeout': 3,
    'watch_interval': 2,
    'watch_threshold': 1.0,
    'watch_heartbeat_interval': 10,
    'refresh_interval': 3,
    'refresh_interval_off_hours': 60,
    'cache_ttl_multiplier': 2,
    'cache_freshness_warn_secs': 30,
}

_cached_config = None


def _deep_merge(base, override):
    """递归深度合并字典，override 覆盖 base"""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config():
    """加载配置文件，带缓存。嵌套 dict 深度合并。"""
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            user_cfg = json.load(f)
        _cached_config = _deep_merge(DEFAULT_CONFIG, user_cfg)
        return _cached_config
    _cached_config = dict(DEFAULT_CONFIG)
    return _cached_config


def reload_config():
    """清除配置缓存，下次 load_config 重新读取"""
    global _cached_config
    _cached_config = None


def save_config(cfg):
    """保存配置到 config.json 并更新缓存"""
    global _cached_config
    config_dir = os.path.dirname(CONFIG_PATH)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _cached_config = cfg


def ensure_data_dir():
    """确保数据目录存在"""
    os.makedirs(DATA_DIR, exist_ok=True)
