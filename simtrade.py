#!/usr/bin/env python3
"""SimTrade - A股模拟交易系统 (LLM CLI)"""

import argparse
import csv
import datetime
import json
import os
import sys
import time

import requests
import pandas as pd

# === 1. 配置与常量 ===

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
CONFIG_PATH = os.path.join(SCRIPT_DIR, 'config.json')
PORTFOLIO_PATH = os.path.join(DATA_DIR, 'portfolio.json')
TRADES_PATH = os.path.join(DATA_DIR, 'trades.csv')
NAMES_PATH = os.path.join(DATA_DIR, 'stock_names.json')
STRATEGY_PATH = os.path.join(DATA_DIR, 'strategy.json')

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
    st = json.loads(requests.get(URL, timeout=3).content)
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
    st = json.loads(requests.get(URL, timeout=3).content)
    buf = st['data'][code]['m' + str(ts)]
    df = pd.DataFrame(buf, columns=['time', 'open', 'close', 'high', 'low', 'volume', 'n1', 'n2'])
    df = df[['time', 'open', 'close', 'high', 'low', 'volume']]
    df[['open', 'close', 'high', 'low', 'volume']] = df[['open', 'close', 'high', 'low', 'volume']].astype('float')
    df.time = pd.to_datetime(df.time)
    df.set_index(['time'], inplace=True)
    df.index.name = ''
    if 'qt' in st['data'][code] and code in st['data'][code]['qt']:
        df.iloc[-1, df.columns.get_loc('close')] = float(st['data'][code]['qt'][code][3])
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
    r = requests.get(URL, timeout=3)
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


def get_batch_realtime_prices(codes):
    """批量获取实时行情，一次请求获取多只股票的价格和名称"""
    if not codes:
        return {}
    result = {}
    codes_str = ','.join(codes)
    try:
        url = f'http://qt.gtimg.cn/q={codes_str}'
        r = requests.get(url, timeout=3)
        for line in r.text.strip().split(';'):
            line = line.strip()
            if not line or '=' not in line:
                continue
            key, val = line.split('=', 1)
            val = val.strip('"')
            if not val:
                continue
            parts = val.split('~')
            code = key.split('_')[-1] if '_' in key else key
            if len(parts) > 3:
                name = parts[1]
                price = float(parts[3])
                save_stock_name(code, name)
                result[code] = {'price': price, 'name': name}
    except Exception:
        pass
    return result


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
        r = requests.get(url, timeout=3)
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


# === 5. CLI 命令处理 ===

def cmd_init(args):
    """初始化账户"""
    cash = args.cash if args.cash else load_config().get('default_cash', DEFAULT_CONFIG['default_cash'])
    ensure_data_dir()
    portfolio = {
        'account_id': 'sim_001',
        'cash': float(cash),
        'positions': {},
        'initial_cash': float(cash),
        'created_at': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'updated_at': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    }
    save_portfolio(portfolio)
    if os.path.exists(TRADES_PATH):
        os.remove(TRADES_PATH)
    json_output({
        'status': 'ok',
        'message': '账户初始化成功',
        'cash': portfolio['cash'],
        'account_id': portfolio['account_id'],
    })


def cmd_status(args):
    """查看账户状态"""
    portfolio = require_portfolio()
    cfg = load_config()
    positions = []
    total_market_value = 0.0
    total_cost = 0.0
    codes = list(portfolio['positions'].keys())
    batch = get_batch_realtime_prices(codes) if codes else {}
    for code, pos in portfolio['positions'].items():
        if code in batch:
            current_price = batch[code]['price']
        else:
            try:
                current_price = get_realtime_price(code)
            except Exception:
                current_price = pos['avg_cost']
        market_value = current_price * pos['qty']
        unrealized = (current_price - pos['avg_cost']) * pos['qty']
        total_market_value += market_value
        total_cost += pos['avg_cost'] * pos['qty']
        positions.append({
            'code': code,
            'name': pos.get('name', code),
            'qty': pos['qty'],
            'avg_cost': pos['avg_cost'],
            'current_price': round(current_price, 2),
            'market_value': round(market_value, 2),
            'unrealized_pnl': round(unrealized, 2),
        })
    total_assets = portfolio['cash'] + total_market_value
    total_pnl = total_assets - portfolio['initial_cash']
    total_pnl_pct = (total_pnl / portfolio['initial_cash'] * 100) if portfolio['initial_cash'] else 0
    json_output({
        'cash': round(portfolio['cash'], 2),
        'positions': positions,
        'total_assets': round(total_assets, 2),
        'total_market_value': round(total_market_value, 2),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'initial_cash': portfolio['initial_cash'],
    })


def cmd_quote(args):
    """获取实时行情"""
    code = args.code
    try:
        price = get_realtime_price(code)
        name = get_stock_name(code)
        json_output({
            'code': code,
            'name': name,
            'price': price,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        })
    except Exception as e:
        json_error(f'获取行情失败: {e}')


def cmd_quotes(args):
    """批量获取行情"""
    codes = [c.strip() for c in args.codes.split(',')]
    batch = get_batch_realtime_prices(codes)
    results = []
    for code in codes:
        if code in batch:
            results.append({
                'code': code,
                'name': batch[code]['name'],
                'price': batch[code]['price'],
            })
        else:
            try:
                price = get_realtime_price(code)
                name = get_stock_name(code)
                results.append({
                    'code': code,
                    'name': name,
                    'price': price,
                })
            except Exception as e:
                results.append({
                    'code': code,
                    'error': str(e),
                })
    json_output({'quotes': results, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')})


def cmd_buy(args):
    """限价买入"""
    result = execute_buy(args.code, args.price, args.qty, reason=getattr(args, 'reason', ''), force=args.force)
    json_output(result)


def cmd_sell(args):
    """限价卖出"""
    result = execute_sell(args.code, args.price, args.qty, reason=getattr(args, 'reason', ''), force=args.force)
    json_output(result)


def cmd_buy_market(args):
    """市价买入"""
    cfg = load_config()
    try:
        price = get_realtime_price(args.code)
    except Exception as e:
        json_error(f'获取行情失败: {e}')
    slip = cfg.get('slippage', DEFAULT_CONFIG['slippage'])
    price = round(price * (1 + slip), 2)
    result = execute_buy(args.code, price, args.qty, reason=getattr(args, 'reason', ''), force=args.force)
    result['slippage'] = slip
    result['executed_price'] = price
    json_output(result)


def cmd_sell_market(args):
    """市价卖出"""
    cfg = load_config()
    try:
        price = get_realtime_price(args.code)
    except Exception as e:
        json_error(f'获取行情失败: {e}')
    slip = cfg.get('slippage', DEFAULT_CONFIG['slippage'])
    price = round(price * (1 - slip), 2)
    result = execute_sell(args.code, price, args.qty, reason=getattr(args, 'reason', ''), force=args.force)
    result['slippage'] = slip
    result['executed_price'] = price
    json_output(result)


def cmd_history(args):
    """查看历史交易记录"""
    trades = load_trades()
    json_output({'trades': trades, 'count': len(trades)})


def cmd_pnl(args):
    """盈亏统计"""
    portfolio = require_portfolio()
    trades = load_trades()

    realized_pnl = 0.0
    sell_trades = [t for t in trades if t.get('action') == 'sell']
    for t in sell_trades:
        realized_pnl += float(t.get('amount', 0)) - float(t.get('commission', 0))

    unrealized_pnl = 0.0
    codes = list(portfolio['positions'].keys())
    batch = get_batch_realtime_prices(codes) if codes else {}
    for code, pos in portfolio['positions'].items():
        if code in batch:
            current_price = batch[code]['price']
        else:
            try:
                current_price = get_realtime_price(code)
            except Exception:
                current_price = pos['avg_cost']
        unrealized_pnl += (current_price - pos['avg_cost']) * pos['qty']

    total_pnl = realized_pnl + unrealized_pnl
    total_pnl_pct = (total_pnl / portfolio['initial_cash'] * 100) if portfolio['initial_cash'] else 0

    json_output({
        'initial_cash': portfolio['initial_cash'],
        'current_cash': round(portfolio['cash'], 2),
        'realized_pnl': round(realized_pnl, 2),
        'unrealized_pnl': round(unrealized_pnl, 2),
        'total_pnl': round(total_pnl, 2),
        'total_pnl_pct': round(total_pnl_pct, 2),
        'total_trades': len(trades),
        'sell_trades': len(sell_trades),
    })


def cmd_reset(args):
    """重置账户"""
    portfolio = load_portfolio()
    initial = portfolio['initial_cash'] if portfolio else load_config().get('default_cash', DEFAULT_CONFIG['default_cash'])
    ensure_data_dir()
    portfolio = {
        'account_id': 'sim_001',
        'cash': float(initial),
        'positions': {},
        'initial_cash': float(initial),
        'created_at': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'updated_at': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    }
    save_portfolio(portfolio)
    if os.path.exists(TRADES_PATH):
        os.remove(TRADES_PATH)
    json_output({'status': 'ok', 'message': '账户已重置', 'cash': portfolio['cash']})


def cmd_report(args):
    """交易复盘报告"""
    trades = load_trades()
    if not trades:
        json_output({'summary': {'total_trades': 0}, 'round_trips': []})

    last_n = args.last if args.last else len(trades)

    # 按代码分组，配对买卖
    buy_queue = {}  # code -> list of buy trades (FIFO)
    round_trips = []

    for t in trades:
        code = t['code']
        action = t['action']
        if action == 'buy':
            if code not in buy_queue:
                buy_queue[code] = []
            buy_queue[code].append(t)
        elif action == 'sell':
            if code in buy_queue and buy_queue[code]:
                buy_t = buy_queue[code].pop(0)
                buy_price = float(buy_t['price'])
                sell_price = float(t['price'])
                qty = int(t['qty'])
                sell_amount = float(t.get('amount', sell_price * qty))
                sell_commission = float(t.get('commission', 0))
                buy_amount = float(buy_t.get('amount', buy_price * qty))
                pnl = sell_amount - buy_amount - sell_commission
                pnl_pct = (pnl / buy_amount * 100) if buy_amount else 0
                try:
                    bt = datetime.datetime.strptime(buy_t['timestamp'], '%Y-%m-%dT%H:%M:%S')
                    st = datetime.datetime.strptime(t['timestamp'], '%Y-%m-%dT%H:%M:%S')
                    holding_sec = (st - bt).total_seconds()
                    h = int(holding_sec // 3600)
                    m = int((holding_sec % 3600) // 60)
                    s = int(holding_sec % 60)
                    holding_time = f'{h}:{m:02d}:{s:02d}'
                except Exception:
                    holding_time = 'N/A'
                round_trips.append({
                    'code': code,
                    'name': t.get('name', code),
                    'buy_time': buy_t['timestamp'],
                    'sell_time': t['timestamp'],
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'qty': qty,
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'holding_time': holding_time,
                })

    # 未配对的买入 = 持仓中
    open_positions = []
    codes_with_positions = []
    for code, buys in buy_queue.items():
        for b in buys:
            open_positions.append({'code': code, 'buy_price': float(b['price']), 'qty': int(b['qty']), 'name': b.get('name', code)})
            if code not in codes_with_positions:
                codes_with_positions.append(code)

    # 获取持仓当前价
    batch = get_batch_realtime_prices(codes_with_positions) if codes_with_positions else {}
    for p in open_positions:
        current = batch.get(p['code'], {}).get('price', p['buy_price'])
        p['current_price'] = current
        p['unrealized_pnl'] = round((current - p['buy_price']) * p['qty'], 2)

    # 取最近 N 笔 round trips
    round_trips = round_trips[-last_n:] if last_n < len(round_trips) else round_trips

    # 汇总统计
    profits = [r['pnl'] for r in round_trips if r['pnl'] > 0]
    losses = [r['pnl'] for r in round_trips if r['pnl'] <= 0]
    total_realized = sum(r['pnl'] for r in round_trips)
    avg_profit = sum(profits) / len(profits) if profits else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(sum(profits) / sum(losses)) if losses and sum(losses) != 0 else float('inf') if profits else 0

    json_output({
        'summary': {
            'total_trades': len(trades),
            'buy_trades': len([t for t in trades if t['action'] == 'buy']),
            'sell_trades': len([t for t in trades if t['action'] == 'sell']),
            'round_trips': len(round_trips),
            'win_count': len(profits),
            'loss_count': len(losses),
            'win_rate': round(len(profits) / len(round_trips) * 100, 2) if round_trips else 0,
            'total_realized_pnl': round(total_realized, 2),
            'avg_profit': round(avg_profit, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
        },
        'round_trips': round_trips,
        'open_positions': open_positions,
    })


def fetch_with_fallback(codes):
    """批量获取行情，失败时逐只回退"""
    batch = get_batch_realtime_prices(codes)
    missing = [c for c in codes if c not in batch]
    for code in missing:
        try:
            price = get_realtime_price(code)
            name = get_stock_name(code)
            batch[code] = {'price': price, 'name': name}
        except Exception:
            pass
    return batch


def cmd_watch(args):
    """持续监控行情，价格变动超阈值时输出信号"""
    codes = [c.strip() for c in args.codes.split(',')]
    threshold = args.threshold if args.threshold else 1.0
    interval = args.interval if args.interval else 5

    # 获取基准价格
    batch = fetch_with_fallback(codes)
    base_prices = {}
    for code in codes:
        if code in batch:
            base_prices[code] = batch[code]['price']
            print(json.dumps({
                'type': 'start',
                'code': code,
                'name': batch[code]['name'],
                'base_price': batch[code]['price'],
                'threshold': threshold,
                'interval': interval,
            }, ensure_ascii=False))
        else:
            print(json.dumps({'type': 'error', 'code': code, 'message': f'无法获取 {code} 行情'}, ensure_ascii=False))
            return

    sys.stdout.flush()
    last_alert_prices = dict(base_prices)
    poll_count = 0

    try:
        while True:
            time.sleep(interval)
            poll_count += 1
            batch = fetch_with_fallback(codes)
            for code in codes:
                if code not in batch:
                    continue
                current = batch[code]['price']
                base = base_prices[code]
                last = last_alert_prices[code]
                change_from_base = (current - base) / base * 100

                if abs(current - last) / last * 100 >= threshold:
                    direction = 'up' if current > last else 'down'
                    print(json.dumps({
                        'type': 'alert',
                        'code': code,
                        'name': batch[code]['name'],
                        'base_price': base,
                        'prev_price': last,
                        'current_price': current,
                        'change_pct': round((current - last) / last * 100, 2),
                        'total_change_pct': round(change_from_base, 2),
                        'direction': direction,
                        'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                    }, ensure_ascii=False))
                    sys.stdout.flush()
                    last_alert_prices[code] = current

            # 心跳：每10次轮询
            if poll_count % 10 == 0:
                prices = {code: batch.get(code, {}).get('price', base_prices[code]) for code in codes}
                print(json.dumps({
                    'type': 'heartbeat',
                    'prices': prices,
                    'poll_count': poll_count,
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                }, ensure_ascii=False))
                sys.stdout.flush()

    except KeyboardInterrupt:
        # 输出最终汇总
        batch = fetch_with_fallback(codes)
        final_prices = {}
        for code in codes:
            current = batch.get(code, {}).get('price', base_prices[code])
            base = base_prices[code]
            final_prices[code] = {
                'base_price': base,
                'current_price': current,
                'change_pct': round((current - base) / base * 100, 2),
            }
        print(json.dumps({
            'type': 'summary',
            'poll_count': poll_count,
            'duration_seconds': poll_count * interval,
            'prices': final_prices,
            'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        }, ensure_ascii=False))
        sys.stdout.flush()


def load_strategy():
    """加载策略文件"""
    if not os.path.exists(STRATEGY_PATH):
        return {'rules': []}
    try:
        with open(STRATEGY_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'rules': []}


def check_rules(rules, prices):
    """检查策略规则是否触发，返回触发的规则列表"""
    triggered = []
    for rule in rules:
        code = rule['code']
        if code not in prices:
            continue
        current = prices[code]['price']
        rtype = rule['type']
        params = rule.get('params', {})
        fired = False
        if rtype == 'price_above' and current >= params['price']:
            fired = True
        elif rtype == 'price_below' and current <= params['price']:
            fired = True
        elif rtype == 'change_above':
            base = params.get('base_price', current)
            if base > 0 and (current - base) / base * 100 >= params['pct']:
                fired = True
        elif rtype == 'change_below':
            base = params.get('base_price', current)
            if base > 0 and (current - base) / base * 100 <= -params['pct']:
                fired = True
        if fired:
            triggered.append({
                'rule_name': rule.get('name', ''),
                'type': rtype,
                'code': code,
                'name': prices[code]['name'],
                'current_price': current,
                'params': params,
                'action': rule.get('action', 'alert'),
            })
    return triggered


def cmd_strategy(args):
    """策略管理"""
    subcmd = args.strategy_cmd

    if subcmd == 'list':
        strategy = load_strategy()
        json_output(strategy)

    elif subcmd == 'load':
        if not os.path.exists(STRATEGY_PATH):
            json_error(f'策略文件不存在: {STRATEGY_PATH}，请先创建 data/strategy.json')
        strategy = load_strategy()
        json_output({
            'status': 'ok',
            'message': f'已加载 {len(strategy.get("rules", []))} 条策略',
            'rules_count': len(strategy.get('rules', [])),
        })

    elif subcmd == 'apply':
        code = args.code
        strategy = load_strategy()
        rules = [r for r in strategy.get('rules', []) if r['code'] == code]
        if not rules:
            json_error(f'没有针对 {code} 的策略规则')
        batch = get_batch_realtime_prices([code])
        if code not in batch:
            json_error(f'无法获取 {code} 行情')
        triggered = check_rules(rules, batch)
        json_output({
            'code': code,
            'current_price': batch[code]['price'],
            'rules_checked': len(rules),
            'triggered': triggered,
            'has_signal': len(triggered) > 0,
        })

    else:
        json_error('未知策略子命令，使用 list / load / apply')


# === 6. main 入口 ===

def main():
    parser = argparse.ArgumentParser(description='SimTrade - A股模拟交易系统')
    sub = parser.add_subparsers(dest='command', help='可用命令')

    p_init = sub.add_parser('init', help='初始化账户')
    p_init.add_argument('--cash', type=float, help='初始资金')

    sub.add_parser('status', help='查看账户状态')

    p_quote = sub.add_parser('quote', help='获取实时行情')
    p_quote.add_argument('code', help='股票代码 (如 sh600519)')

    p_quotes = sub.add_parser('quotes', help='批量获取行情')
    p_quotes.add_argument('codes', help='股票代码，逗号分隔 (如 sh600519,sz000858)')

    p_buy = sub.add_parser('buy', help='限价买入')
    p_buy.add_argument('code', help='股票代码')
    p_buy.add_argument('price', type=float, help='委托价格')
    p_buy.add_argument('qty', type=int, help='数量（100 的倍数）')
    p_buy.add_argument('--force', action='store_true', help='绕过交易时间检查')
    p_buy.add_argument('--reason', type=str, default='', help='交易备注')

    p_sell = sub.add_parser('sell', help='限价卖出')
    p_sell.add_argument('code', help='股票代码')
    p_sell.add_argument('price', type=float, help='委托价格')
    p_sell.add_argument('qty', type=int, help='数量（100 的倍数）')
    p_sell.add_argument('--force', action='store_true', help='绕过交易时间检查')
    p_sell.add_argument('--reason', type=str, default='', help='交易备注')

    p_bm = sub.add_parser('buy_market', help='市价买入')
    p_bm.add_argument('code', help='股票代码')
    p_bm.add_argument('qty', type=int, help='数量（100 的倍数）')
    p_bm.add_argument('--force', action='store_true', help='绕过交易时间检查')
    p_bm.add_argument('--reason', type=str, default='', help='交易备注')

    p_sm = sub.add_parser('sell_market', help='市价卖出')
    p_sm.add_argument('code', help='股票代码')
    p_sm.add_argument('qty', type=int, help='数量（100 的倍数）')
    p_sm.add_argument('--force', action='store_true', help='绕过交易时间检查')
    p_sm.add_argument('--reason', type=str, default='', help='交易备注')

    sub.add_parser('history', help='查看历史交易记录')
    sub.add_parser('pnl', help='盈亏统计')
    sub.add_parser('reset', help='重置账户')

    p_report = sub.add_parser('report', help='交易复盘报告')
    p_report.add_argument('--last', type=int, help='最近N笔')

    p_watch = sub.add_parser('watch', help='持续监控行情')
    p_watch.add_argument('codes', help='股票代码，逗号分隔')
    p_watch.add_argument('--threshold', type=float, help='变动告警阈值(百分比)，默认1.0')
    p_watch.add_argument('--interval', type=int, help='轮询间隔(秒)，默认5')

    p_strategy = sub.add_parser('strategy', help='策略管理')
    p_strategy_sub = p_strategy.add_subparsers(dest='strategy_cmd', help='策略子命令')
    p_strategy_sub.add_parser('list', help='查看当前策略')
    p_strategy_sub.add_parser('load', help='加载策略文件')
    p_apply = p_strategy_sub.add_parser('apply', help='对指定股票应用策略')
    p_apply.add_argument('code', help='股票代码')

    args = parser.parse_args()

    commands = {
        'init': cmd_init,
        'status': cmd_status,
        'quote': cmd_quote,
        'quotes': cmd_quotes,
        'buy': cmd_buy,
        'sell': cmd_sell,
        'buy_market': cmd_buy_market,
        'sell_market': cmd_sell_market,
        'history': cmd_history,
        'pnl': cmd_pnl,
        'reset': cmd_reset,
        'report': cmd_report,
        'watch': cmd_watch,
        'strategy': cmd_strategy,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
