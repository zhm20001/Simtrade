# SimTrade 操作指南（LLM 用）

## 快速开始

```bash
cd ~/simtrade

# 1. 初始化账户（首次或需要重置时）
python simtrade.py init --cash 1000000

# 2. 查看账户状态
python simtrade.py status

# 3. 查看某只股票实时行情
python simtrade.py quote sh600519
```

## 项目结构

```
simtrade/
  simtrade.py          # CLI 入口（薄壳）
  config.json          # 用户配置（可选，覆盖默认值）
  core/
    __init__.py
    config.py           # 配置管理
    engine.py           # 交易引擎（Engine 类）
    market.py           # 行情服务
  data/                 # 运行时数据（gitignore）
    portfolio.json      # 账户状态
    trades.csv          # 交易记录
    stock_names.json    # 股票名称缓存
    strategy.json       # 策略规则
```

## 股票代码格式

- 上海交易所：`sh` + 6位代码，如 `sh600519`（贵州茅台）
- 深圳交易所：`sz` + 6位代码，如 `sz000858`（五粮液）
- 指数：`sh000001`（上证）、`sz399001`（深证）

## 交易命令

```bash
# 限价买入（指定价格和数量，数量必须为100的倍数）
python simtrade.py buy sh600519 1500.00 100 --force --reason "你的分析理由"

# 限价卖出
python simtrade.py sell sh600519 1550.00 100 --force --reason "止盈"

# 市价买入（自动获取当前价格成交，含0.1%滑点）
python simtrade.py buy_market sh600519 100 --force --reason "突破买入"

# 市价卖出
python simtrade.py sell_market sh600519 100 --force --reason "止损"
```

**注意：** `--force` 用于绕过交易时段限制。在实盘时段（09:15-11:30, 13:00-15:30）内可省略。

## 查看数据

```bash
# 批量行情（一次请求获取多只股票，高效）
python simtrade.py quotes sh600519,sz000858,sh601318

# 历史交易记录
python simtrade.py history

# 盈亏统计（已实现 + 未实现，配对买卖计算）
python simtrade.py pnl
```

**性能说明：** `quotes`、`status`、`pnl` 使用腾讯批量行情接口，多只股票仅 1 次网络请求。单只股票的 `quote` 和市价交易保持独立请求。

## 批量行情返回字段

`quotes` 命令返回每只股票的完整行情信息：

| 字段 | 说明 |
|------|------|
| `price` | 当前价格 |
| `name` | 股票名称 |
| `change` | 涨跌额 |
| `change_pct` | 涨跌幅(%) |
| `volume` | 成交量（手） |
| `turnover` | 换手率(%) |
| `high` | 最高价 |
| `low` | 最低价 |
| `open` | 开盘价 |

## 典型交易流程

```bash
# 第一步：初始化
python simtrade.py init --cash 1000000

# 第二步：选股 - 查看多只候选股票行情
python simtrade.py quotes sh600519,sz000858,sh601318,sz300750

# 第三步：分析后决策 - 市价买入
python simtrade.py buy_market sh600519 100 --force --reason "放量突破20日均线，MACD金叉"

# 第四步：确认持仓和浮盈
python simtrade.py status

# 第五步：持续监控（watch 模式，价格变动超阈值自动输出信号）
python simtrade.py watch sh600519 --threshold 0.5 --interval 3

# 第六步：达到目标后卖出
python simtrade.py sell_market sh600519 100 --force --reason "涨幅达标，获利了结"

# 第七步：复盘
python simtrade.py pnl
python simtrade.py report
```

## 复盘报告

```bash
# 全部交易复盘（自动配对买卖，计算胜率、盈亏比、持仓时长）
python simtrade.py report

# 最近5笔
python simtrade.py report --last 5
```

输出包含：`summary`（汇总统计：胜率、盈亏比）+ `round_trips`（每笔完整交易）+ `open_positions`（当前持仓浮盈）。

## 行情监控（watch）

```bash
# 持续监控，价格变动超1%时输出信号
python simtrade.py watch sh600519,sh600900

# 自定义阈值和轮询间隔
python simtrade.py watch sh600519,sh600900 --threshold 0.5 --interval 3
```

Ctrl+C 终止时输出汇总。输出格式为逐行 JSON：
- `type: "start"` — 启动时输出基准价格
- `type: "alert"` — 价格变动超阈值
- `type: "heartbeat"` — 每10次轮询的心跳
- `type: "summary"` — 终止时的最终汇总

## 策略系统

在 `data/strategy.json` 中定义交易规则，系统自动检测触发条件。

```bash
# 查看当前策略
python simtrade.py strategy list

# 加载策略文件
python simtrade.py strategy load

# 对指定股票应用策略
python simtrade.py strategy apply sh600519

# 检查所有策略
python simtrade.py strategy apply
```

**策略文件格式** (`data/strategy.json`)：

```json
{
  "rules": [
    {"name": "止损", "type": "price_below", "code": "sh600011", "params": {"price": 8.00}, "action": "alert"},
    {"name": "止盈", "type": "price_above", "code": "sh600011", "params": {"price": 9.00}, "action": "alert"},
    {"name": "涨幅达标", "type": "change_above", "code": "sh600900", "params": {"pct": 2.0, "base_price": 27.50}, "action": "alert"},
    {"name": "跌幅预警", "type": "change_below", "code": "sh600900", "params": {"pct": 1.5, "base_price": 27.50}, "action": "alert"}
  ]
}
```

**策略类型：**
- `price_above` — 价格突破指定值
- `price_below` — 价格跌破指定值
- `change_above` — 涨幅超过指定百分比
- `change_below` — 跌幅超过指定百分比

## 配置管理

```bash
# 查看当前配置
python simtrade.py config show

# 修改配置项
python simtrade.py config set watch_interval 3
python simtrade.py config set request_timeout 5

# 重新加载配置（清除缓存）
python simtrade.py config reload
```

**支持点号路径：**
```bash
python simtrade.py config set trading_hours.morning.0 09:30
```

**可配置参数：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `default_cash` | 1000000 | 默认初始资金 |
| `commission_rate` | 0.0003 | 佣金费率（万三） |
| `stamp_tax_rate` | 0.001 | 印花税率（千一，仅卖出） |
| `min_commission` | 5.0 | 最低佣金（元） |
| `slippage` | 0.001 | 滑点（千一，仅市价单） |
| `request_timeout` | 3 | 网络请求超时（秒） |
| `watch_interval` | 2 | 监控轮询间隔（秒） |
| `watch_threshold` | 1.0 | 监控告警阈值（%） |
| `watch_heartbeat_interval` | 10 | 心跳间隔（轮询次数） |
| `trading_hours` | 见默认值 | 交易时段配置 |

## 输出格式

所有命令输出 JSON，可直接解析。示例：

```json
{
  "status": "ok",
  "action": "buy",
  "code": "sh600519",
  "name": "贵州茅台",
  "price": 1500.0,
  "qty": 100,
  "amount": 150000.0,
  "commission": 45.0,
  "cash_after": 849955.0
}
```

错误时输出：
```json
{
  "error": "资金不足：需要 150045.00，可用 100000.00"
}
```

## 交易成本

| 项目 | 费率 |
|------|------|
| 佣金 | 万三（最低5元） |
| 印花税 | 千一（仅卖出） |
| 滑点 | 0.1%（仅市价单） |

## 交易规则

- 买入数量必须为 100 的整数倍（A股1手=100股）
- 不能透支（买入金额+手续费 ≤ 可用资金）
- 不能卖空（卖出数量 ≤ 持仓数量）

## 重置

```bash
# 重置账户到初始状态（保留初始金额）
python simtrade.py reset

# 或重新初始化指定金额
python simtrade.py init --cash 500000
```

## 程序化调用（供 UI 或外部系统集成）

```python
from core.engine import Engine
from core.market import get_batch_realtime_prices

engine = Engine()
result = engine.buy("sh600519", 1500.00, 100, force=True, reason="程序化买入")
print(result)  # dict，不含 sys.exit

quotes = get_batch_realtime_prices(["sh600519", "sz000858"])
print(quotes)  # {code: {price, name, change, ...}}
```
