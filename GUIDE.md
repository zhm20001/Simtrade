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
# 批量行情
python simtrade.py quotes sh600519,sz000858,sh601318

# 历史交易记录
python simtrade.py history

# 盈亏统计（已实现 + 未实现）
python simtrade.py pnl
```

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

# 第五步：持续监控（每1秒可重复执行）
python simtrade.py quote sh600519

# 第六步：达到目标后卖出
python simtrade.py sell_market sh600519 100 --force --reason "涨幅达标，获利了结"

# 第七步：复盘
python simtrade.py pnl
python simtrade.py history
```

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
