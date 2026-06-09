# SimTrade 方案 B 改进路线：多模块架构

> 当前为方案 A（单文件），当 simtrade.py 超过 800 行或需要多脚本 import 时，可按此文档重构。

## 目标结构

```
~/simtrade/
├── simtrade/                # Python 包
│   ├── __init__.py
│   ├── cli.py               # CLI 入口，argparse 命令分发
│   ├── market.py            # 行情获取（封装 Ashare）
│   ├── broker.py            # 交易引擎（买卖、验资、手续费）
│   ├── storage.py           # 数据持久化（portfolio/trades/names）
│   └── config.py            # 配置加载与默认值
├── run.py                   # 入口：python run.py <command>
├── config.json
├── data/
└── docs/
```

## 模块职责

### market.py — 行情层
- 内嵌 Ashare 行情函数
- `get_realtime_price(code)` — 获取最新价
- `get_batch_prices(codes)` — 批量获取
- `resolve_stock_name(code)` — 查询并缓存股票名称

### broker.py — 交易引擎
- `buy(code, price, qty, ...)` — 限价买入
- `sell(code, price, qty, ...)` — 限价卖出
- `buy_market(code, qty, ...)` — 市价买入
- `sell_market(code, qty, ...)` — 市价卖出
- `get_status()` — 账户状态
- `get_pnl()` — 盈亏计算
- 交易规则校验、手续费计算

### storage.py — 持久化层
- `load_portfolio()` / `save_portfolio()`
- `load_trades()` / `append_trade()`
- `load_names()` / `save_name()`

### config.py — 配置层
- `load_config()` — 加载 config.json，合并默认值
- 默认值定义

### cli.py — 命令层
- argparse 命令定义
- 调用 broker/market/storage
- JSON 输出格式化

## 迁移步骤

1. 创建 `simtrade/` 包目录和 `__init__.py`
2. 从 simtrade.py 提取行情函数 → `market.py`
3. 提取 portfolio/trades 读写函数 → `storage.py`
4. 提取交易逻辑 → `broker.py`
5. 提取配置常量 → `config.py`
6. 提取 argparse 和命令分发 → `cli.py`
7. 创建 `run.py` 作为入口
8. 验证所有命令行为不变

## 触发条件

当以下任一条件满足时考虑重构：
- simtrade.py 超过 800 行
- 需要被其他 Python 脚本 import（而非仅 CLI 调用）
- 需要写单元测试（模块化后更容易测试）
- 需要添加 HTTP API 层（可复用 broker/market 模块）
