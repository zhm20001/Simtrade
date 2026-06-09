#!/usr/bin/env python3
"""SimTrade - A股模拟交易系统 (LLM CLI)

薄壳 CLI，所有业务逻辑在 core/ 模块中。
"""

import argparse
import datetime
import json
import sys

from core.config import load_config, reload_config, save_config
from core.engine import Engine
from core.market import (
    get_realtime_price,
    get_stock_name,
    get_batch_realtime_prices,
    fetch_with_fallback,
    get_price,
)
from core.config import STRATEGY_PATH
import os


def json_output(data, exit_code=0):
    """统一 JSON 输出"""
    print(json.dumps(data, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def json_error(msg, exit_code=1):
    """统一错误输出"""
    json_output({'error': msg}, exit_code)


def safe_execute(func, *args, **kwargs):
    """执行引擎方法，捕获异常转为 JSON 错误输出"""
    try:
        result = func(*args, **kwargs)
        json_output(result)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        json_error(str(e))
    except Exception as e:
        json_error(f'{type(e).__name__}: {e}')


# === CLI 命令处理 ===

def cmd_init(args):
    engine = Engine()
    safe_execute(engine.init, cash=args.cash)


def cmd_status(args):
    engine = Engine()
    safe_execute(engine.status)


def cmd_quote(args):
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
    codes = [c.strip() for c in args.codes.split(',')]
    batch = get_batch_realtime_prices(codes)
    results = []
    for code in codes:
        if code in batch:
            info = {'code': code, 'name': batch[code]['name'], 'price': batch[code]['price']}
            # 附加字段（如果有的话）
            for key in ['change', 'change_pct', 'volume', 'turnover', 'high', 'low', 'open']:
                if key in batch[code]:
                    info[key] = batch[code][key]
            results.append(info)
        else:
            try:
                price = get_realtime_price(code)
                name = get_stock_name(code)
                results.append({'code': code, 'name': name, 'price': price})
            except Exception as e:
                results.append({'code': code, 'error': str(e)})
    json_output({'quotes': results, 'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')})


def cmd_buy(args):
    engine = Engine()
    safe_execute(engine.buy, args.code, args.price, args.qty,
                 reason=getattr(args, 'reason', ''), force=args.force)


def cmd_sell(args):
    engine = Engine()
    safe_execute(engine.sell, args.code, args.price, args.qty,
                 reason=getattr(args, 'reason', ''), force=args.force)


def cmd_buy_market(args):
    engine = Engine()
    safe_execute(engine.buy_market, args.code, args.qty,
                 reason=getattr(args, 'reason', ''), force=args.force)


def cmd_sell_market(args):
    engine = Engine()
    safe_execute(engine.sell_market, args.code, args.qty,
                 reason=getattr(args, 'reason', ''), force=args.force)


def cmd_history(args):
    engine = Engine()
    safe_execute(engine.history)


def cmd_pnl(args):
    engine = Engine()
    safe_execute(engine.pnl)


def cmd_reset(args):
    engine = Engine()
    safe_execute(engine.reset)


def cmd_report(args):
    engine = Engine()
    safe_execute(engine.report, last_n=args.last)


def cmd_watch(args):
    """持续监控行情，价格变动超阈值时输出信号"""
    import time

    codes = [c.strip() for c in args.codes.split(',')]
    cfg = load_config()
    threshold = args.threshold if args.threshold else cfg.get('watch_threshold', 1.0)
    interval = args.interval if args.interval else cfg.get('watch_interval', 2)
    heartbeat_interval = cfg.get('watch_heartbeat_interval', 10)

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

            if poll_count % heartbeat_interval == 0:
                prices = {code: batch.get(code, {}).get('price', base_prices[code]) for code in codes}
                print(json.dumps({
                    'type': 'heartbeat',
                    'prices': prices,
                    'poll_count': poll_count,
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
                }, ensure_ascii=False))
                sys.stdout.flush()

    except KeyboardInterrupt:
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


def cmd_strategy(args):
    engine = Engine()
    subcmd = args.strategy_cmd

    if subcmd == 'list':
        safe_execute(engine.strategy_list)
    elif subcmd == 'load':
        safe_execute(engine.strategy_load)
    elif subcmd == 'apply':
        safe_execute(engine.strategy_apply, code=args.code)
    else:
        json_error('未知策略子命令，使用 list / load / apply')


def cmd_config(args):
    """配置管理"""
    subcmd = args.config_cmd

    if subcmd == 'show':
        cfg = load_config()
        json_output({'config': cfg})
    elif subcmd == 'set':
        key = args.key
        value = args.value
        cfg = load_config()

        # 尝试解析为数字
        try:
            if '.' in value:
                value = float(value)
            else:
                value = int(value)
        except ValueError:
            pass  # keep as string

        # 支持点号路径，如 trading_hours.morning.0
        keys = key.split('.')
        target = cfg
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

        save_config(cfg)
        json_output({'status': 'ok', 'message': f'已设置 {key} = {value}'})
    elif subcmd == 'reload':
        reload_config()
        json_output({'status': 'ok', 'message': '配置已重新加载'})
    else:
        json_error('未知配置子命令，使用 show / set / reload')


# === main 入口 ===

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
    p_watch.add_argument('--interval', type=int, help='轮询间隔(秒)，默认2')

    p_strategy = sub.add_parser('strategy', help='策略管理')
    p_strategy_sub = p_strategy.add_subparsers(dest='strategy_cmd', help='策略子命令')
    p_strategy_sub.add_parser('list', help='查看当前策略')
    p_strategy_sub.add_parser('load', help='加载策略文件')
    p_apply = p_strategy_sub.add_parser('apply', help='对指定股票应用策略')
    p_apply.add_argument('code', help='股票代码（省略则检查所有）', nargs='?', default=None)

    p_config = sub.add_parser('config', help='配置管理')
    p_config_sub = p_config.add_subparsers(dest='config_cmd', help='配置子命令')
    p_config_sub.add_parser('show', help='查看当前配置')
    p_config_sub.add_parser('reload', help='重新加载配置')
    p_set = p_config_sub.add_parser('set', help='设置配置项')
    p_set.add_argument('key', help='配置键（支持点号路径，如 trading_hours.morning.0）')
    p_set.add_argument('value', help='配置值')

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
        'config': cmd_config,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
