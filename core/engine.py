"""交易引擎 — 买卖执行、持仓管理、费用计算、数据持久化"""

import csv
import datetime
import json
import os
import sys

if sys.platform != 'win32':
    import fcntl

from core.config import (
    load_config, ensure_data_dir, DEFAULT_CONFIG,
    PORTFOLIO_PATH, TRADES_PATH, STRATEGY_PATH,
)
from core.market import get_stock_name, get_realtime_price, get_batch_realtime_prices


def _flock(f, exclusive=True):
    if sys.platform == 'win32':
        return
    op = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    fcntl.flock(f, op)


def _funlock(f):
    if sys.platform == 'win32':
        return
    fcntl.flock(f, fcntl.LOCK_UN)


# --- 交易时段 ---

def is_trading_hours(cfg=None):
    """检查当前是否在交易时段"""
    if cfg is None:
        cfg = load_config()
    now = datetime.datetime.now().strftime('%H:%M')
    hours = cfg.get('trading_hours', DEFAULT_CONFIG['trading_hours'])
    in_morning = hours['morning'][0] <= now <= hours['morning'][1]
    in_afternoon = hours['afternoon'][0] <= now <= hours['afternoon'][1]
    return in_morning or in_afternoon


# --- 费用计算 ---

def calc_commission(amount, cfg=None):
    """计算买入佣金"""
    if cfg is None:
        cfg = load_config()
    rate = cfg.get('commission_rate', DEFAULT_CONFIG['commission_rate'])
    min_c = cfg.get('min_commission', DEFAULT_CONFIG['min_commission'])
    return round(max(amount * rate, min_c), 2)


def calc_sell_cost(amount, cfg=None):
    """计算卖出总手续费（佣金 + 印花税）"""
    if cfg is None:
        cfg = load_config()
    commission = calc_commission(amount, cfg)
    stamp_rate = cfg.get('stamp_tax_rate', DEFAULT_CONFIG['stamp_tax_rate'])
    stamp_tax = round(amount * stamp_rate, 2)
    return round(commission + stamp_tax, 2)


# --- 数据持久化 ---

def load_portfolio():
    """加载账户状态"""
    if not os.path.exists(PORTFOLIO_PATH):
        return None
    try:
        with open(PORTFOLIO_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        raise ValueError('portfolio.json 格式损坏，请运行 reset 重置')


def save_portfolio(portfolio):
    """保存账户状态（带文件锁）"""
    ensure_data_dir()
    portfolio['updated_at'] = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    # round cash
    portfolio['cash'] = round(portfolio['cash'], 2)
    with open(PORTFOLIO_PATH, 'w', encoding='utf-8') as f:
        _flock(f)
        json.dump(portfolio, f, ensure_ascii=False, indent=2)
        _funlock(f)


def append_trade(trade_record):
    """追加一条交易记录到 trades.csv（带文件锁）"""
    ensure_data_dir()
    file_exists = os.path.exists(TRADES_PATH) and os.path.getsize(TRADES_PATH) > 0
    with open(TRADES_PATH, 'a', newline='', encoding='utf-8') as f:
        _flock(f)
        writer = csv.DictWriter(f, fieldnames=[
            'timestamp', 'action', 'code', 'name', 'price', 'qty',
            'amount', 'commission', 'cash_after', 'reason'
        ])
        if not file_exists:
            writer.writeheader()
        writer.writerow(trade_record)
        _funlock(f)


def load_trades():
    """加载所有交易记录"""
    if not os.path.exists(TRADES_PATH):
        return []
    try:
        with open(TRADES_PATH, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return [
                {k: _auto_convert(v) for k, v in row.items()}
                for row in reader
            ]
    except Exception:
        return []


def _auto_convert(val):
    """CSV 读出的是字符串，尝试转数值类型"""
    try:
        return int(val)
    except (ValueError, TypeError):
        pass
    try:
        return float(val)
    except (ValueError, TypeError):
        return val


def require_portfolio():
    """获取账户状态，不存在则抛异常"""
    p = load_portfolio()
    if p is None:
        raise RuntimeError('账户未初始化，请先运行 init')
    return p


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
                'name': prices[code].get('name', code),
                'current_price': current,
                'params': params,
                'action': rule.get('action', 'alert'),
            })
    return triggered


# --- Engine 类 ---

class Engine:
    """交易引擎 — 所有交易操作通过此类执行"""

    def __init__(self, cfg=None):
        self.cfg = cfg or load_config()

    def init(self, cash=None):
        """初始化账户，返回结果 dict"""
        if cash is None:
            cash = self.cfg.get('default_cash', DEFAULT_CONFIG['default_cash'])
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
        return {
            'status': 'ok',
            'message': '账户初始化成功',
            'cash': portfolio['cash'],
            'account_id': portfolio['account_id'],
        }

    def reset(self):
        """重置账户到初始金额，返回结果 dict"""
        portfolio = load_portfolio()
        initial = portfolio['initial_cash'] if portfolio else self.cfg.get('default_cash', DEFAULT_CONFIG['default_cash'])
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
        return {'status': 'ok', 'message': '账户已重置', 'cash': portfolio['cash']}

    def buy(self, code, price, qty, reason='', force=False):
        """限价买入，返回结果 dict 或抛异常"""
        self._check_trading_hours(force)
        portfolio = require_portfolio()

        if qty <= 0 or qty % 100 != 0:
            raise ValueError('买入数量必须为 100 的整数倍')

        amount = round(price * qty, 2)
        commission = calc_commission(amount, self.cfg)
        total_cost = round(amount + commission, 2)

        if total_cost > portfolio['cash']:
            raise ValueError(f'资金不足：需要 {total_cost:.2f}，可用 {portfolio["cash"]:.2f}')

        name = get_stock_name(code)
        portfolio['cash'] = round(portfolio['cash'] - total_cost, 2)

        if code in portfolio['positions']:
            pos = portfolio['positions'][code]
            total_qty = pos['qty'] + qty
            pos['avg_cost'] = round((pos['avg_cost'] * pos['qty'] + price * qty) / total_qty, 4)
            pos['qty'] = total_qty
            pos['trades'] += 1
            pos['name'] = name
        else:
            portfolio['positions'][code] = {
                'code': code,
                'name': name,
                'qty': qty,
                'avg_cost': round(price, 4),
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
            'amount': amount,
            'commission': commission,
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
            'amount': amount,
            'commission': commission,
            'cash_after': round(portfolio['cash'], 2),
        }

    def sell(self, code, price, qty, reason='', force=False):
        """限价卖出，返回结果 dict 或抛异常"""
        self._check_trading_hours(force)
        portfolio = require_portfolio()

        if code not in portfolio['positions']:
            raise ValueError(f'未持有 {code}')

        pos = portfolio['positions'][code]
        if qty <= 0 or qty % 100 != 0:
            raise ValueError('卖出数量必须为 100 的整数倍')
        if qty > pos['qty']:
            raise ValueError(f'持仓不足：持有 {pos["qty"]} 股，尝试卖出 {qty} 股')

        amount = round(price * qty, 2)
        total_fee = calc_sell_cost(amount, self.cfg)

        name = pos.get('name', get_stock_name(code))
        portfolio['cash'] = round(portfolio['cash'] + amount - total_fee, 2)

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
            'amount': amount,
            'commission': total_fee,
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
            'amount': amount,
            'commission': total_fee,
            'cash_after': round(portfolio['cash'], 2),
        }

    def buy_market(self, code, qty, reason='', force=False):
        """市价买入（含滑点），返回结果 dict 或抛异常"""
        price = get_realtime_price(code)
        slip = self.cfg.get('slippage', DEFAULT_CONFIG['slippage'])
        price = round(price * (1 + slip), 2)
        result = self.buy(code, price, qty, reason=reason, force=force)
        result['slippage'] = slip
        result['executed_price'] = price
        return result

    def sell_market(self, code, qty, reason='', force=False):
        """市价卖出（含滑点），返回结果 dict 或抛异常"""
        price = get_realtime_price(code)
        slip = self.cfg.get('slippage', DEFAULT_CONFIG['slippage'])
        price = round(price * (1 - slip), 2)
        result = self.sell(code, price, qty, reason=reason, force=force)
        result['slippage'] = slip
        result['executed_price'] = price
        return result

    def status(self):
        """查看账户状态，返回结果 dict"""
        portfolio = require_portfolio()
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
            market_value = round(current_price * pos['qty'], 2)
            unrealized = round((current_price - pos['avg_cost']) * pos['qty'], 2)
            total_market_value += market_value
            total_cost += pos['avg_cost'] * pos['qty']
            positions.append({
                'code': code,
                'name': pos.get('name', code),
                'qty': pos['qty'],
                'avg_cost': pos['avg_cost'],
                'current_price': round(current_price, 2),
                'market_value': market_value,
                'unrealized_pnl': unrealized,
            })
        total_assets = round(portfolio['cash'] + total_market_value, 2)
        total_pnl = round(total_assets - portfolio['initial_cash'], 2)
        total_pnl_pct = round((total_pnl / portfolio['initial_cash'] * 100), 2) if portfolio['initial_cash'] else 0
        return {
            'cash': round(portfolio['cash'], 2),
            'positions': positions,
            'total_assets': total_assets,
            'total_market_value': round(total_market_value, 2),
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'initial_cash': portfolio['initial_cash'],
        }

    def history(self):
        """查看历史交易记录，返回结果 dict"""
        trades = load_trades()
        return {'trades': trades, 'count': len(trades)}

    def pnl(self):
        """盈亏统计，返回结果 dict"""
        portfolio = require_portfolio()
        trades = load_trades()

        # 按代码分组配对买卖计算已实现盈亏
        realized_pnl = 0.0
        buy_queue = {}
        for t in trades:
            code = t['code']
            action = t.get('action', '')
            if action == 'buy':
                buy_queue.setdefault(code, []).append(t)
            elif action == 'sell':
                if code in buy_queue and buy_queue[code]:
                    buy_t = buy_queue[code].pop(0)
                    sell_amount = float(t.get('amount', float(t['price']) * int(t['qty'])))
                    sell_commission = float(t.get('commission', 0))
                    buy_amount = float(buy_t.get('amount', float(buy_t['price']) * int(buy_t['qty'])))
                    buy_commission = float(buy_t.get('commission', 0))
                    realized_pnl += (sell_amount - sell_commission) - (buy_amount + buy_commission)

        # 未实现盈亏
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

        total_pnl = round(realized_pnl + unrealized_pnl, 2)
        total_pnl_pct = round((total_pnl / portfolio['initial_cash'] * 100), 2) if portfolio['initial_cash'] else 0

        return {
            'initial_cash': portfolio['initial_cash'],
            'current_cash': round(portfolio['cash'], 2),
            'realized_pnl': round(realized_pnl, 2),
            'unrealized_pnl': round(unrealized_pnl, 2),
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'total_trades': len(trades),
            'sell_trades': len([t for t in trades if t.get('action') == 'sell']),
        }

    def report(self, last_n=None):
        """交易复盘报告，返回结果 dict"""
        trades = load_trades()
        if not trades:
            return {'summary': {'total_trades': 0}, 'round_trips': [], 'open_positions': []}

        if last_n is None:
            last_n = len(trades)

        buy_queue = {}
        round_trips = []

        for t in trades:
            code = t['code']
            action = t.get('action', '')
            if action == 'buy':
                buy_queue.setdefault(code, []).append(t)
            elif action == 'sell':
                if code in buy_queue and buy_queue[code]:
                    buy_t = buy_queue[code].pop(0)
                    buy_price = float(buy_t['price'])
                    sell_price = float(t['price'])
                    qty = int(t['qty'])
                    sell_amount = float(t.get('amount', sell_price * qty))
                    sell_commission = float(t.get('commission', 0))
                    buy_amount = float(buy_t.get('amount', buy_price * qty))
                    buy_commission = float(buy_t.get('commission', 0))
                    pnl = round((sell_amount - sell_commission) - (buy_amount + buy_commission), 2)
                    pnl_pct = round((pnl / buy_amount * 100), 2) if buy_amount else 0
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
                        'pnl': pnl,
                        'pnl_pct': pnl_pct,
                        'holding_time': holding_time,
                    })

        # 未配对的买入 = 持仓中
        open_positions = []
        codes_with_positions = []
        for code, buys in buy_queue.items():
            for b in buys:
                open_positions.append({
                    'code': code,
                    'buy_price': float(b['price']),
                    'qty': int(b['qty']),
                    'name': b.get('name', code),
                })
                if code not in codes_with_positions:
                    codes_with_positions.append(code)

        batch = get_batch_realtime_prices(codes_with_positions) if codes_with_positions else {}
        for p in open_positions:
            current = batch.get(p['code'], {}).get('price', p['buy_price'])
            p['current_price'] = current
            p['unrealized_pnl'] = round((current - p['buy_price']) * p['qty'], 2)

        round_trips = round_trips[-last_n:] if last_n < len(round_trips) else round_trips

        profits = [r['pnl'] for r in round_trips if r['pnl'] > 0]
        losses = [r['pnl'] for r in round_trips if r['pnl'] <= 0]
        total_realized = round(sum(r['pnl'] for r in round_trips), 2)
        avg_profit = round(sum(profits) / len(profits), 2) if profits else 0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0
        profit_factor = round(abs(sum(profits) / sum(losses)), 2) if losses and sum(losses) != 0 else float('inf') if profits else 0

        return {
            'summary': {
                'total_trades': len(trades),
                'buy_trades': len([t for t in trades if t.get('action') == 'buy']),
                'sell_trades': len([t for t in trades if t.get('action') == 'sell']),
                'round_trips': len(round_trips),
                'win_count': len(profits),
                'loss_count': len(losses),
                'win_rate': round(len(profits) / len(round_trips) * 100, 2) if round_trips else 0,
                'total_realized_pnl': total_realized,
                'avg_profit': avg_profit,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
            },
            'round_trips': round_trips,
            'open_positions': open_positions,
        }

    def strategy_list(self):
        """查看当前策略"""
        return load_strategy()

    def strategy_load(self):
        """加载策略文件"""
        if not os.path.exists(STRATEGY_PATH):
            raise FileNotFoundError(f'策略文件不存在: {STRATEGY_PATH}，请先创建 data/strategy.json')
        strategy = load_strategy()
        return {
            'status': 'ok',
            'message': f'已加载 {len(strategy.get("rules", []))} 条策略',
            'rules_count': len(strategy.get('rules', [])),
        }

    def strategy_apply(self, code=None):
        """对指定股票或所有持仓应用策略"""
        strategy = load_strategy()
        rules = strategy.get('rules', [])

        if code:
            rules = [r for r in rules if r['code'] == code]
            if not rules:
                raise ValueError(f'没有针对 {code} 的策略规则')
            codes_to_fetch = [code]
        else:
            # apply all: 检查所有策略涉及的股票
            codes_to_fetch = list(set(r['code'] for r in rules))
            if not codes_to_fetch:
                raise ValueError('没有可应用的策略规则')

        batch = get_batch_realtime_prices(codes_to_fetch)
        triggered = check_rules(rules, batch)

        results = []
        for c in codes_to_fetch:
            if c in batch:
                rule_count = len([r for r in rules if r['code'] == c])
                trig = [t for t in triggered if t['code'] == c]
                results.append({
                    'code': c,
                    'current_price': batch[c]['price'],
                    'rules_checked': rule_count,
                    'triggered': trig,
                    'has_signal': len(trig) > 0,
                })

        if code:
            return results[0] if results else {'code': code, 'error': '无法获取行情'}
        return {'results': results, 'total_triggered': len(triggered)}

    def _check_trading_hours(self, force=False):
        """检查交易时间"""
        if force:
            return
        if not is_trading_hours(self.cfg):
            now = datetime.datetime.now().strftime('%H:%M')
            raise ValueError(
                f'当前 {now} 不在交易时段 (09:15-11:30, 13:00-15:30)，使用 --force 可绕过'
            )
