#!/usr/bin/env python3
"""SimTrade - A股模拟交易系统 (LLM CLI)"""

import argparse
import csv
import datetime
import json
import os
import sys

import requests
import pandas as pd

# === 1. 配置与常量 ===

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')
PORTFOLIO_PATH = os.path.join(DATA_DIR, 'portfolio.json')
TRADES_PATH = os.path.join(DATA_DIR, 'trades.csv')
NAMES_PATH = os.path.join(DATA_DIR, 'stock_names.json')

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
    'data_dir': './data',
}


def load_config():
    """加载配置文件，不存在则返回默认值"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            user_cfg = json.load(f)
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(user_cfg)
        return cfg
    return dict(DEFAULT_CONFIG)


def ensure_data_dir():
    """确保数据目录存在"""
    os.makedirs(DATA_DIR, exist_ok=True)


def json_output(data, exit_code=0):
    """统一 JSON 输出"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def json_error(msg, exit_code=1):
    """统一错误输出"""
    json_output({'error': msg}, exit_code)
