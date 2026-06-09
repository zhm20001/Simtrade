"""行情服务 — 实时行情、批量行情、历史K线、股票名称缓存"""

import datetime
import json
import os

import pandas as pd
import requests

from core.config import load_config, ensure_data_dir, NAMES_PATH


# --- 股票名称缓存 ---

_names_cache = None
_names_dirty = False


def _load_names():
    """加载股票名称到内存缓存"""
    global _names_cache
    if _names_cache is not None:
        return _names_cache
    if os.path.exists(NAMES_PATH):
        with open(NAMES_PATH, 'r', encoding='utf-8') as f:
            _names_cache = json.load(f)
    else:
        _names_cache = {}
    return _names_cache


def save_stock_name(code, name):
    """保存股票名称到内存缓存，延迟写入磁盘"""
    global _names_cache, _names_dirty
    if _names_cache is None:
        _load_names()
    _names_cache[code] = name
    _names_dirty = True


def flush_names():
    """将脏数据刷写到磁盘"""
    global _names_dirty
    if _names_dirty and _names_cache is not None:
        ensure_data_dir()
        with open(NAMES_PATH, 'w', encoding='utf-8') as f:
            json.dump(_names_cache, f, ensure_ascii=False, indent=2)
        _names_dirty = False


def get_stock_name(code):
    """获取股票名称，优先内存缓存，再磁盘缓存，最后接口获取"""
    names = _load_names()
    if code in names:
        return names[code]
    try:
        url = f'http://qt.gtimg.cn/q={code}'
        cfg = load_config()
        r = requests.get(url, timeout=cfg.get('request_timeout', 3))
        r.encoding = 'gbk'
        parts = r.text.split('~')
        if len(parts) > 1:
            name = parts[1]
            save_stock_name(code, name)
            return name
    except Exception:
        pass
    return code


# --- K线数据（Ashare 内嵌） ---

def get_price_day_tx(code, end_date='', count=10, frequency='1d'):
    unit = 'week' if frequency in '1w' else 'month' if frequency in '1M' else 'day'
    if end_date:
        end_date = end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date.split(' ')[0]
    end_date = '' if end_date == datetime.datetime.now().strftime('%Y-%m-%d') else end_date
    URL = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},{unit},,{end_date},{count},qfq'
    timeout = load_config().get('request_timeout', 3)
    st = json.loads(requests.get(URL, timeout=timeout).content)
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
    timeout = load_config().get('request_timeout', 3)
    st = json.loads(requests.get(URL, timeout=timeout).content)
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
    timeout = load_config().get('request_timeout', 3)
    r = requests.get(URL, timeout=timeout)
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
    """获取最新成交价，带错误处理"""
    df = get_price(code, frequency='1m', count=1)
    if df is None or len(df) == 0:
        raise ValueError(f'无法获取 {code} 的行情数据')
    return float(df.iloc[-1]['close'])


def get_batch_realtime_prices(codes):
    """批量获取实时行情，一次请求获取多只股票。返回 {code: {price, name, ...}}"""
    if not codes:
        return {}
    result = {}
    codes_str = ','.join(codes)
    try:
        url = f'http://qt.gtimg.cn/q={codes_str}'
        cfg = load_config()
        r = requests.get(url, timeout=cfg.get('request_timeout', 3))
        r.encoding = 'gbk'
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
                info = {'price': price, 'name': name}
                if len(parts) > 38:
                    info['change'] = float(parts[31]) if parts[31] else 0
                    info['change_pct'] = float(parts[32]) if parts[32] else 0
                    info['volume'] = float(parts[36]) if parts[36] else 0
                    info['amount'] = float(parts[37]) * 10000 if parts[37] else 0  # 万元 → 元
                    info['turnover'] = float(parts[38]) if parts[38] else 0
                    info['high'] = float(parts[33]) if parts[33] else price
                    info['low'] = float(parts[34]) if parts[34] else price
                    info['open'] = float(parts[5]) if parts[5] else price
                result[code] = info
        flush_names()
    except Exception:
        pass
    return result


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
