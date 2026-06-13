"""Verify Engine uses cache instead of direct market API."""

from unittest.mock import patch
import pytest

from core.engine import Engine, load_portfolio, save_portfolio


def test_buy_market_uses_cache_not_market(tmp_data_dir, fresh_cache, write_fake_cache, monkeypatch):
    """buy_market should fail with CacheError when code not in cache, NOT call market."""
    # Empty cache (sh600519 not present)
    write_fake_cache({}, age_secs=1)

    # Patch market module to detect any direct API call
    import core.market as market_mod
    monkeypatch.setattr(market_mod, 'get_realtime_price',
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('should not call market directly')))
    monkeypatch.setattr(market_mod, 'get_batch_realtime_prices',
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('should not call market directly')))

    eng = Engine()
    eng.init(cash=100000)
    # buy_market on a code not in cache should raise cache error, not call market
    with pytest.raises(Exception) as exc_info:
        eng.buy_market('sh600519', 100, force=True)
    msg = str(exc_info.value).lower()
    assert 'cache' in msg or 'not in monitor' in msg


def test_status_uses_cache(tmp_data_dir, fresh_cache, write_fake_cache, monkeypatch):
    """status() should read from cache, not call market directly."""
    write_fake_cache({
        'sh600519': {'price': 1700.0, 'name': '贵州茅台'},
    }, age_secs=1)

    import core.market as market_mod
    monkeypatch.setattr(market_mod, 'get_realtime_price',
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('should not call market directly')))
    monkeypatch.setattr(market_mod, 'get_batch_realtime_prices',
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError('should not call market directly')))

    eng = Engine()
    eng.init(cash=100000)
    # Manually add a position so status has something to value
    portfolio = load_portfolio()
    portfolio['positions']['sh600519'] = {
        'code': 'sh600519', 'name': '贵州茅台', 'qty': 100, 'avg_cost': 1600.0, 'trades': 1,
    }
    save_portfolio(portfolio)

    result = eng.status()
    # Find the position
    pos = next(p for p in result['positions'] if p['code'] == 'sh600519')
    assert pos['current_price'] == 1700.0  # came from cache, not market
