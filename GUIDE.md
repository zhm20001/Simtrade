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

# 盈亏统计（已实现 + 未实现）
python simtrade.py pnl
```

**性能说明：** `quotes`、`status`、`pnl` 使用腾讯批量行情接口，多只股票仅 1 次网络请求。单只股票的 `quote` 和市价交易保持独立请求。

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

# 对指定股票应用策略（检查是否触发）
python simtrade.py strategy apply sh600519
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
