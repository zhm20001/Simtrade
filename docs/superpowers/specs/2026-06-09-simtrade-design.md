# SimTrade 模拟交易系统设计文档

> 日期：2026-06-09
> 状态：已批准

## 概述

CLI 模拟交易系统，供外部 LLM（如 Claude Code）通过 shell 调用，进行 A 股短线模拟交易。基于 Ashare（mpquant/Ashare）代码框架获取腾讯/新浪行情数据。

## 架构：方案 A（单文件）

```
~/simtrade/
├── simtrade.py              # 主程序（~500-600 行）
├── config.json              # 可选配置
├── data/                    # 运行时自动创建
│   ├── portfolio.json
│   ├── trades.csv
│   └── stock_names.json
└── docs/
    └── upgrade-to-module.md
```

## CLI 命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `init` | 初始化账户 | `python simtrade.py init --cash 1000000` |
| `status` | 账户状态（资金、持仓、市值） | `python simtrade.py status` |
| `quote <code>` | 实时行情 | `python simtrade.py quote sh600519` |
| `quotes <codes>` | 批量行情（逗号分隔） | `python simtrade.py quotes sh600519,sz000858` |
| `buy <code> <price> <qty>` | 限价买入 | `python simtrade.py buy sh600519 1850.00 100` |
| `sell <code> <price> <qty>` | 限价卖出 | `python simtrade.py sell sh600519 1860.00 100` |
| `buy_market <code> <qty>` | 市价买入 | `python simtrade.py buy_market sh600519 100` |
| `sell_market <code> <qty>` | 市价卖出 | `python simtrade.py sell_market sh600519 100` |
| `history` | 历史交易记录 | `python simtrade.py history` |
| `pnl` | 盈亏统计 | `python simtrade.py pnl` |
| `reset` | 重置账户 | `python simtrade.py reset` |

- 所有输出为 JSON 格式
- 交易命令默认检查交易时间，`--force` 可绕过
- `buy`/`sell`/`buy_market`/`sell_market` 支持 `--reason` 参数传入备注

## 交易时间

- 默认交易时段：09:15-11:30、13:00-15:30
- 可通过 `--force` 绕过（用于测试和回测）
- config.json 中可自定义时段

## 数据模型

### portfolio.json（账户状态）

```json
{
  "account_id": "sim_001",
  "cash": 950000.00,
  "positions": {
    "sh600519": {
      "code": "sh600519",
      "name": "贵州茅台",
      "qty": 200,
      "avg_cost": 1850.00,
      "trades": 2
    }
  },
  "initial_cash": 1000000.00,
  "created_at": "2026-06-09T09:15:00",
  "updated_at": "2026-06-09T10:30:15"
}
```

### trades.csv（交易记录）

| 字段 | 说明 |
|------|------|
| timestamp | 成交时间 ISO 8601 |
| action | buy / sell |
| code | 股票代码 |
| name | 股票名称 |
| price | 成交价格 |
| qty | 成交数量 |
| amount | 成交金额 |
| commission | 手续费 |
| cash_after | 成交后可用资金 |
| reason | 备注 |

### stock_names.json（名称映射缓存）

首次遇到新股票代码时通过接口查询名称并缓存。

## 交易成本

| 项目 | 费率 | 说明 |
|------|------|------|
| 佣金 | 万三 (0.0003) | 最低 5 元 |
| 印花税 | 千一 (0.001) | 仅卖出 |
| 滑点 | 0.1% | 市价单模拟 |

可通过 config.json 调整。

## 交易引擎逻辑

### 买入流程

1. 检查交易时间（除非 --force）
2. 获取实时价格（限价单用用户指定价格）
3. 验证：qty 为 100 整数倍
4. 验证：资金充足（amount + 手续费 ≤ cash）
5. 计算佣金：max(price × qty × 0.0003, 5)
6. 扣减现金，增加持仓（更新 avg_cost）
7. 写入 trades.csv，更新 portfolio.json
8. 输出 JSON 结果

### 卖出流程

1. 检查交易时间（除非 --force）
2. 验证：持仓充足（qty ≤ position.qty）
3. 计算佣金 + 印花税
4. 增加现金，减少持仓（qty=0 时移除）
5. 写入 trades.csv，更新 portfolio.json
6. 输出 JSON 结果

### 交易规则

- 买入数量必须为 100 的整数倍
- 禁止卖空
- 禁止透支
- 涨跌停价格范围检查（前收盘价 ±10%，ST 股 ±5%）

### 市价单

- 获取当前实时价格
- 滑点模拟：买入价 × (1 + slippage)，卖出价 × (1 - slippage)
- 然后走限价逻辑

## 行情获取

- 内嵌 Ashare 核心代码（~80 行），不依赖外部文件
- 数据源：新浪主力 + 腾讯备用
- 分钟线走腾讯接口
- `quote` 命令调用 `get_price(code, frequency='1m', count=1)` 取最新价
- 无额外限流，由 LLM 侧控制请求节奏

## 错误处理

- 所有错误输出 JSON：`{"error": "描述"}`，exit code 1
- 网络超时/接口异常返回明确信息，不静默重试
- 文件损坏时提示并建议 `reset`

## 依赖

仅 `requests`、`pandas`，无需额外安装。

## 代码组织（simtrade.py 内部）

```
# === 1. 配置与常量 ===         ~30 行
# === 2. 行情获取（Ashare 内嵌）=== ~80 行
# === 3. 数据持久化 ===         ~80 行
# === 4. 交易引擎 ===          ~150 行
# === 5. CLI 命令处理 ===       ~120 行
# === 6. main 入口 ===         ~40 行
```

## LLM 使用模式

LLM（如 Claude Code）的典型工作流：

```
1. python simtrade.py init --cash 1000000        # 初始化
2. python simtrade.py quote sh600519              # 查看行情
3. [LLM 分析行情，自主决策]
4. python simtrade.py buy_market sh600519 100 --reason "突破20日均线"  # 买入
5. python simtrade.py status                      # 查看持仓
6. [等待一段时间，持续监控]
7. python simtrade.py sell_market sh600519 100 --reason "止盈"         # 卖出
8. python simtrade.py pnl                         # 查看盈亏
```

循环 2-7，在交易时段内每秒获取行情并自主决策。
