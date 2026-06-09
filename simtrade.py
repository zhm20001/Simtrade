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


# === 2. 行情获取（Ashare 内嵌）===

def get_price_day_tx(code, end_date='', count=10, frequency='1d'):
    unit = 'week' if frequency in '1w' else 'month' if frequency in '1M' else 'day'
    if end_date:
        end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date.split(' ')[0]
    end_date = '' if end_date == datetime.datetime.now().strftime('%Y-%m-%d') else end_date
    URL = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{unit},,{end_date},{count},qfq'
    st = json.loads(requests.get(URL, timeout=10).content)
    ms = 'qfq' + unit
    stk = st['data'][code]
    buf = stk[ms] if ms in stk else stk[unit]
    df = pd.DataFrame(buf)
    df.columns = ['time', 'open', 'close', 'high', 'low', 'volume']
    df[['open', 'close', 'high', 'low', 'volume']] = df[['open', 'close', 'high', 'low', 'volume']].astype('float')
    df.time = pd.to_datetime(df.time)
    df.set_index(['time'], inplace=True)
    df.index.name = ''
    return df


def get_price_min_tx(code, end_date=None, count=10, frequency='1d'):
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1
    if end_date:
        end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date.split(' ')[0]
    URL = f'http://ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},m{ts},,{count}'
    st = json.loads(requests.get(URL, timeout=10).content)
    buf = st['data'][code]['m' + str(ts)]
    df = pd.DataFrame(buf, columns=['time', 'open', 'close', 'high', 'low', 'volume', 'n1', 'n2'])
    df = df[['time', 'open', 'close', 'high', 'low', 'volume']]
    df[['open', 'close', 'high', 'low', 'volume']] = df[['open', 'close', 'high', 'low', 'volume']].astype('float')
    df.time = pd.to_datetime(df.time)
    df.set_index(['time'], inplace=True)
    df.index.name = ''
    if 'qt' in st['data'][code] and code in st['data'][code]['qt']:
        df['close'].iloc[-1] = float(st['data'][code]['qt'][code][3])
    return df


def get_price_sina(code, end_date='', count=10, frequency='60m'):
    frequency = frequency.replace('1d', '240m').replace('1w', '1200m').replace('1M', '7200m')
    mcount = count
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1
    if (end_date != '') & (frequency in ['240m', '1200m', '7200m']):
        end_date = pd.to_datetime(end_date) if not isinstance(end_date, datetime.date) else end_date
        unit = 4 if frequency == '1200m' else 29 if frequency == '7200m' else 1
        count = count + (datetime.datetime.now() - end_date).days // unit
    URL = f'http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code}&scale={ts}&ma=5&datalen={count}'
    r = requests.get(URL, timeout=10)
    dstr = json.loads(r.content.decode('gbk', errors='ignore'))
    df = pd.DataFrame(dstr)
    if 'day' in df.columns:
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        df.day = pd.to_datetime(df.day)
        df.set_index(['day'], inplace=True)
        df.index.name = ''
        if (end_date != '') & (frequency in ['240m', '1200m', '7200m']):
            return df[df.index <= end_date][-mcount:]
        return df
    return pd.DataFrame()


def get_price(code, end_date='', count=10, frequency='1d'):
    xcode = code.replace('.XSHG', '').replace('.XSHE', '')
    xcode = 'sh' + xcode if ('XSHG' in code) else 'sz' + xcode if ('XSHE' in code) else code
    if frequency in ['1d', '1w', '1M']:
        try:
            df = get_price_sina(xcode, end_date=end_date, count=count, frequency=frequency)
            if df is not None and len(df) > 0:
                return df
            return get_price_day_tx(xcode, end_date=end_date, count=count, frequency=frequency)
        except Exception:
            return get_price_day_tx(xcode, end_date=end_date, count=count, frequency=frequency)
    if frequency in ['1m', '5m', '15m', '30m', '60m']:
        if frequency == '1m':
            return get_price_min_tx(xcode, end_date=end_date, count=count, frequency=frequency)
        try:
            df = get_price_sina(xcode, end_date=end_date, count=count, frequency=frequency)
            if df is not None and len(df) > 0:
                return df
            return get_price_min_tx(xcode, end_date=end_date, count=count, frequency=frequency)
        except Exception:
            return get_price_min_tx(xcode, end_date=end_date, count=count, frequency=frequency)


def get_realtime_price(code):
    """获取最新成交价"""
    df = get_price(code, frequency='1m', count=1)
    return float(df.iloc[-1]['close'])


def load_stock_names():
    """加载股票名称缓存"""
    if os.path.exists(NAMES_PATH):
        with open(NAMES_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_stock_name(code, name):
    """保存股票名称到缓存"""
    names = load_stock_names()
    names[code] = name
    ensure_data_dir()
    with open(NAMES_PATH, 'w', encoding='utf-8') as f:
        json.dump(names, f, ensure_ascii=False, indent=2)


def get_stock_name(code):
    """获取股票名称，优先缓存，否则通过接口获取"""
    names = load_stock_names()
    if code in names:
        return names[code]
    try:
        url = f'http://qt.gtimg.cn/q={code}'
        r = requests.get(url, timeout=10)
        parts = r.text.split('~')
        if len(parts) > 1:
            name = parts[1]
            save_stock_name(code, name)
            return name
    except Exception:
        pass
    return code


# === 3. 数据持久化 ===

def load_portfolio():
    """加载账户状态"""
    if not os.path.exists(PORTFOLIO_PATH):
        return None
    try:
        with open(PORTFOLIO_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        json_error('portfolio.json 格式损坏，请运行 reset 重置')


def save_portfolio(portfolio):
    """保存账户状态"""
    ensure_data_dir()
    portfolio['updated_at'] = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    with open(PORTFOLIO_PATH, 'w', encoding='utf-8') as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)


def append_trade(trade_record):
    """追加一条交易记录到 trades.csv"""
    ensure_data_dir()
    file_exists = os.path.exists(TRADES_PATH) and os.path.getsize(TRADES_PATH) > 0
    with open(TRADES_PATH, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'action', 'code', 'name', 'price', 'qty',
            'amount', 'commission', 'cash_after', 'reason'
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_record)


def load_trades():
    """加载所有交易记录"""
    if not os.path.exists(TRADES_PATH):
        return []
    try:
        df = pd.read_csv(TRADES_PATH, encoding='utf-8')
        return df.to_dict('records')
    except Exception:
        return []


def require_portfolio():
    """获取账户状态，不存在则报错"""
    p = load_portfolio()
    if p is None:
        json_error('账户未初始化，请先运行 init')
    return p


# === 4. 交易引擎 ===

def is_trading_hours(cfg=None):
    """检查当前是否在交易时段"""
    if cfg is None:
        cfg = load_config()
    now = datetime.datetime.now()
    now_str = now.strftime('%H:%M')
    hours = cfg.get('trading_hours', DEFAULT_CONFIG['trading_hours'])
    morning_start = hours['morning'][0]
    morning_end = hours['morning'][1]
    afternoon_start = hours['afternoon'][0]
    afternoon_end = hours['afternoon'][1]
    in_morning = morning_start <= now_str <= morning_end
    in_afternoon = afternoon_start <= now_str <= afternoon_end
    return in_morning or in_afternoon


def check_trading_hours(force=False):
    """检查交易时间，不在交易时间则报错"""
    if force:
        return
    if not is_trading_hours():
        now = datetime.datetime.now().strftime('%H:%M')
        json_error(f'当前 {now} 不在交易时段 (09:15-11:30, 13:00-15:30)，使用 --force 可绕过')


def calc_commission(amount, cfg=None):
    """计算买入佣金"""
    if cfg is None:
        cfg = load_config()
    rate = cfg.get('commission_rate', DEFAULT_CONFIG['commission_rate'])
    min_c = cfg.get('min_commission', DEFAULT_CONFIG['min_commission'])
    return max(amount * rate, min_c)


def calc_sell_cost(amount, cfg=None):
    """计算卖出总手续费（佣金 + 印花税）"""
    if cfg is None:
        cfg = load_config()
    commission = calc_commission(amount, cfg)
    stamp_rate = cfg.get('stamp_tax_rate', DEFAULT_CONFIG['stamp_tax_rate'])
    stamp_tax = amount * stamp_rate
    return commission + stamp_tax


def execute_buy(code, price, qty, reason='', force=False):
    """执行买入"""
    check_trading_hours(force)
    cfg = load_config()
    portfolio = require_portfolio()

    if qty <= 0 or qty % 100 != 0:
        json_error('买入数量必须为 100 的整数倍')

    amount = price * qty
    commission = calc_commission(amount, cfg)
    total_cost = amount + commission

    if total_cost > portfolio['cash']:
        json_error(f'资金不足：需要 {total_cost:.2f}，可用 {portfolio["cash"]:.2f}')

    name = get_stock_name(code)
    portfolio['cash'] -= total_cost

    if code in portfolio['positions']:
        pos = portfolio['positions'][code]
        total_qty = pos['qty'] + qty
        pos['avg_cost'] = (pos['avg_cost'] * pos['qty'] + price * qty) / total_qty
        pos['qty'] = total_qty
        pos['trades'] += 1
        pos['name'] = name
    else:
        portfolio['positions'][code] = {
            'code': code,
            'name': name,
            'qty': qty,
            'avg_cost': price,
            'trades': 1,
        }

    save_portfolio(portfolio)
    trade = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'action': 'buy',
        'code': code,
        'name': name,
        'price': price,
        'qty': qty,
        'amount': round(amount, 2),
        'commission': round(commission, 2),
        'cash_after': round(portfolio['cash'], 2),
        'reason': reason,
    }
    append_trade(trade)
    return {
        'status': 'ok',
        'action': 'buy',
        'code': code,
        'name': name,
        'price': price,
        'qty': qty,
        'amount': round(amount, 2),
        'commission': round(commission, 2),
        'cash_after': round(portfolio['cash'], 2),
    }


def execute_sell(code, price, qty, reason='', force=False):
    """执行卖出"""
    check_trading_hours(force)
    cfg = load_config()
    portfolio = require_portfolio()

    if code not in portfolio['positions']:
        json_error(f'未持有 {code}')

    pos = portfolio['positions'][code]
    if qty <= 0 or qty % 100 != 0:
        json_error('卖出数量必须为 100 的整数倍')
    if qty > pos['qty']:
        json_error(f'持仓不足：持有 {pos["qty"]} 股，尝试卖出 {qty} 股')

    amount = price * qty
    total_fee = calc_sell_cost(amount, cfg)

    name = pos.get('name', get_stock_name(code))
    portfolio['cash'] += amount - total_fee

    pos['qty'] -= qty
    pos['trades'] += 1
    if pos['qty'] == 0:
        del portfolio['positions'][code]

    save_portfolio(portfolio)
    trade = {
        'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'action': 'sell',
        'code': code,
        'name': name,
        'price': price,
        'qty': qty,
        'amount': round(amount, 2),
        'commission': round(total_fee, 2),
        'cash_after': round(portfolio['cash'], 2),
        'reason': reason,
    }
    append_trade(trade)
    return {
        'status': 'ok',
        'action': 'sell',
        'code': code,
        'name': name,
        'price': price,
        'qty': qty,
        'amount': round(amount, 2),
        'commission': round(total_fee, 2),
        'cash_after': round(portfolio['cash'], 2),
    }
