"""Tests for cmd_quote / cmd_quotes reading cache."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta


def _write_cache(data_dir, quotes, age_secs=0, trading_active=True):
    """Write a fresh cache.json into data_dir."""
    cache_path = os.path.join(data_dir, 'cache.json')
    updated_at = (datetime.now() - timedelta(seconds=age_secs)).strftime('%Y-%m-%dT%H:%M:%S')
    with open(cache_path, 'w') as f:
        json.dump({
            'updated_at': updated_at,
            'trading_active': trading_active,
            'quotes': quotes,
        }, f)


def _run_cli(args, data_dir):
    env = dict(os.environ)
    env['SIMTRADE_DATA_DIR'] = str(data_dir)
    return subprocess.run(
        [sys.executable, 'simtrade.py'] + args,
        capture_output=True, text=True, env=env, timeout=10,
    )


def test_quote_reads_cache(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_cache(str(data_dir), {'sh600519': {'price': 1685.5, 'name': '贵州茅台'}})

    result = _run_cli(['quote', 'sh600519'], data_dir)
    assert result.returncode == 0, f'stderr: {result.stderr}'
    data = json.loads(result.stdout)
    assert data['code'] == 'sh600519'
    assert data['price'] == 1685.5
    assert data['name'] == '贵州茅台'


def test_quote_missing_code_errors(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_cache(str(data_dir), {'sh600519': {'price': 1685.5, 'name': '贵州茅台'}})

    result = _run_cli(['quote', 'sz000001'], data_dir)
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert 'error' in data
    assert 'not in monitor' in data['error'] or '不在监控' in data['error']


def test_quote_no_cache_errors(tmp_path):
    """No daemon running, no cache — CLI should report cache missing."""
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    result = _run_cli(['quote', 'sh600519'], data_dir)
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert 'error' in data
    assert 'cache' in data['error'].lower()


def test_quotes_reads_cache(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_cache(str(data_dir), {
        'sh600519': {'price': 1685.5, 'name': '贵州茅台'},
        'sz000858': {'price': 185.0, 'name': '五粮液'},
    })

    result = _run_cli(['quotes', 'sh600519,sz000858'], data_dir)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    codes_to_prices = {q['code']: q.get('price') for q in data['quotes']}
    assert codes_to_prices['sh600519'] == 1685.5
    assert codes_to_prices['sz000858'] == 185.0


def test_quotes_partial_miss(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_cache(str(data_dir), {'sh600519': {'price': 1685.5, 'name': '贵州茅台'}})

    result = _run_cli(['quotes', 'sh600519,sz000001'], data_dir)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    by_code = {q['code']: q for q in data['quotes']}
    assert by_code['sh600519']['price'] == 1685.5
    assert 'error' in by_code['sz000001']
