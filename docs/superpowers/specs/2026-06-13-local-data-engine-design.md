# SimTrade 本地数据 Engine 设计文档

> 日期：2026-06-13
> 状态：已批准
> 分支：`feature/local-data-engine`（基于 `main`）

## 概述

为 simtrade 增加本地数据 engine：一个独立的常驻 daemon 进程，按固定节拍从腾讯 API 拉取行情，原子写入本地 `data/cache.json`；watcher 和 simtrade CLI 从 cache 读取，不再各自直接发外部请求。

**目标**：
- 把外部请求量从"N 个 consumer 各自发"降到"daemon 单一来源"
- 模块化：数据职责（daemon）与展示/交易职责（watcher / CLI）解耦
- 健壮性：daemon 崩溃不影响 consumer（通过文件契约 + 时间戳感知）

**为何作为分支而非合并到 main**：
独立 daemon 只有在"watcher + CLI 同时用"或"CLI 高频调用"场景下才有价值。只想要纯 watcher 盯盘的用户不需要额外进程。新分支保留 main 的纯净，让用户按需切换。

## 已锁定的设计决策

1. **架构**：独立 daemon 进程 + `data/cache.json` 文件广播（方案 3）
2. **生命周期管理**：`simtrade.py engine start/stop/status/restart` 子命令，PID 文件 + subprocess（跨平台）
3. **PID 残留处理**：智能自愈——PID 文件存在时验证进程是否真的死了，死了则清理后启动；活着则报错
4. **无兜底**：consumer 发现 cache 过期/缺失直接报错退出（CLI）或 UI 标注（watcher）。开发期强化反馈，不掩盖问题
5. **配置全部走 config.json**：阈值参数不硬编码
6. **daemon 拉取清单**：`watchlist.json` 全部 code ∪ `portfolio.json` 持仓 code（静态清单）
7. **请求层复用**：daemon 直接 import 并调用 `core/market.get_batch_realtime_prices`，零重写
8. **daemon 单次失败不崩溃**：错误进 log，下个周期重试。consumer 通过 cache 时间戳过期间接感知
9. **watcher-daemon 解耦**：watcher 只看 cache.json 的 `updated_at`，不读 PID 文件
10. **删除 `simtrade.py watch` 子命令**：功能被 watcher.py 完全取代

## 文件结构

```
~/simtrade/
├── simtrade.py              # 改：新增 engine 子命令；quote/quotes/buy/sell/status 改读 cache；删除 watch 子命令
├── watcher.py               # 改：_refresh 读 cache；UI 状态条标注 daemon 异常
├── core/
│   ├── market.py            # 不动（daemon 复用 get_batch_realtime_prices）
│   ├── engine.py            # 改：内部 get_realtime_price 改读 cache
│   ├── config.py            # 改：新增 cache 相关配置项
│   ├── cache.py             # 新增：cache.json 读写（原子写、TTL 判断、错误类型）
│   ├── engine_ctl.py        # 新增：engine start/stop/status/restart（PID + subprocess）
│   └── engine_daemon.py     # 新增：daemon 主循环
├── config.json              # 改：新增 4 个字段
└── data/                    # 运行时（gitignore）
    ├── cache.json           # 新增：daemon 产出
    ├── engine.pid           # 新增：daemon PID
    └── engine.log           # 新增：daemon 日志
```

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│  daemon 进程（独立常驻）                                      │
│  core/engine_daemon.py                                       │
│    while True:                                               │
│      codes = read_watchlist() ∪ read_portfolio()             │
│      batch = core.market.get_batch_realtime_prices(codes)    │
│      trading_active = is_trading_hours()                     │
│      core.cache.write_atomic(batch, trading_active)          │
│      sleep(interval based on trading_active)                 │
└────────────────┬────────────────────────────────────────────┘
                 │ 原子写
                 ▼
            data/cache.json     ← data/engine.pid, data/engine.log

┌─────────────────┐         ┌──────────────────┐
│   watcher.py    │         │   simtrade.py    │
│  (tkinter UI)   │         │   (CLI)          │
│                 │         │                  │
│ _refresh() 每   │ 读文件  │ quote/buy/...    │ 读文件
│ interval 秒读   │ ◀────── │ 读 cache         │ ◀──────
│ cache.json      │         │ TTL 判断         │
│                 │         │ 过期/缺失 → 报错 │
│ cache 过期 →    │         │                  │
│ UI 标注 ⚠       │         │                  │
└─────────────────┘         └──────────────────┘
```

**外部请求量对比**：
- 现状（watcher + CLI 并行）：每 `refresh_interval` 秒 1 次（watcher）+ CLI 每次调用 1 次
- 新方案：仅 daemon 每 `refresh_interval`（交易时段）或 `refresh_interval_off_hours`（非交易时段）1 次

## cache.json 结构

```json
{
  "updated_at": "2026-06-13T14:30:15",
  "trading_active": false,
  "quotes": {
    "sh600519": {
      "name": "贵州茅台",
      "price": 1685.50,
      "change": 12.30,
      "change_pct": 0.73,
      "volume": 12345678,
      "amount": 2000000000,
      "high": 1690.00,
      "low": 1670.00,
      "open": 1675.00,
      "turnover": 0.98
    }
  }
}
```

**字段说明**：

| 字段 | 来源 | 用途 |
|---|---|---|
| `updated_at` | daemon 写入时的时间戳（ISO 8601） | consumer 判断新鲜度 |
| `trading_active` | daemon 计算的 `is_trading_hours()` | watcher UI 灰显；CLI 动态 TTL 判断 |
| `quotes[code]` | `get_batch_realtime_prices` 返回值原样 | 字段集与 `core/market.py` 现状完全一致，watcher 渲染层零改动 |

**契约保证**：
- `quotes[code]` 字段集与 `core/market.get_batch_realtime_prices` 返回值**完全相同**（name, price, change, change_pct, volume, amount, high, low, open, turnover）
- 写入采用原子写（先写 `cache.json.tmp` 再 `os.rename`），reader 永远看到完整的旧文件或完整的新文件

## config.json 新增字段

```json
{
  "refresh_interval": 3,
  "refresh_interval_off_hours": 60,
  "cache_ttl_multiplier": 2,
  "cache_freshness_warn_secs": 30
}
```

| 字段 | 默认值 | 含义 |
|---|---|---|
| `refresh_interval` | 3 | daemon 拉行情的节拍（秒）。同时是 watcher 默认读 cache 节拍 |
| `refresh_interval_off_hours` | 60 | daemon 在非交易时段的拉行情节拍（秒）。保留 commit `64991b9` 的优化 |
| `cache_ttl_multiplier` | 2 | CLI 读 cache 时，过期阈值 = 当前节拍 × 此值 |
| `cache_freshness_warn_secs` | 30 | watcher UI 上"⚠ 缓存过期 Ns"的告警阈值 |

**TTL 动态计算**：
- 交易时段：过期阈值 = `refresh_interval * cache_ttl_multiplier` = 6 秒
- 非交易时段：过期阈值 = `refresh_interval_off_hours * cache_ttl_multiplier` = 120 秒
- consumer 用 cache 里的 `trading_active` 字段判断走哪个 TTL，不自己重算

**Breaking change：`refresh_interval` 迁移**：
- 现状：`refresh_interval` 在 `data/watchlist.json` 里
- 新方案：迁到全局 `config.json`
- 迁移逻辑（watcher 启动时执行）：
  1. 检测 `watchlist.json` 是否有 `refresh_interval` 字段
  2. 若有：读取值 → 写入 `config.json`（若 config 已有则不覆盖）→ 从 `watchlist.json` 删除该字段 → 保存
  3. 若无：跳过
- **不留残留字段，不留双源配置**

## daemon 进程设计（`core/engine_daemon.py`）

### 主循环（伪代码）

```python
def main():
    setup_logging('data/engine.log')
    log('engine daemon starting')
    while True:
        try:
            codes = collect_codes()  # watchlist.json ∪ portfolio.json
            trading_active = is_trading_hours()
            if codes:
                batch = get_batch_realtime_prices(codes)
            else:
                batch = {}
            cache.write_atomic({
                'updated_at': now_iso(),
                'trading_active': trading_active,
                'quotes': batch,
            })
        except Exception as e:
            log_error(e)
            # 不退出，下个周期重试

        interval = config.refresh_interval if is_trading_hours() else config.refresh_interval_off_hours
        sleep(interval)
```

### 关键设计

**1. 错误处理：daemon 不崩溃**
- 单次拉取失败 → 记 log，跳过这次刷新，下个周期重试
- consumer 通过 cache.json 的 `updated_at` 判断"daemon 是否还在更新"
- **理由**：daemon 死了所有 consumer 都瞎；单次失败不该让 daemon 死，错误通过 cache 时间戳过期传导给 consumer 更有用

**2. 清单变化感知**
- 每周期重新读 `watchlist.json` + `portfolio.json`（不缓存）
- 用户在 watcher 加新股票 → daemon 下个周期自动拉到（最多 `refresh_interval` 秒延迟）

**3. 非交易时段行为**
- daemon 不停，仍按节拍拉取（`refresh_interval_off_hours` 秒一次）
- API 在非交易时段返回上一交易日收盘数据，daemon 照写
- `trading_active: false` 让 watcher 做灰显

**4. 日志**
- 路径：`data/engine.log`
- 内容：每次刷新的结果摘要（成功/失败、股票数、耗时）
- 滚动：单文件，超过 1MB 自动截断（保留最后 500KB）

**5. 进程退出**
- 收到 SIGTERM（来自 `engine stop`）→ 优雅退出：写最后一行 log、清理 PID 文件
- 收到 SIGKILL / 崩溃 → PID 文件残留（由 `engine start` 智能自愈处理）

## engine 子命令设计（`core/engine_ctl.py`）

### 命令清单

```bash
simtrade.py engine start     # 启动 daemon
simtrade.py engine stop      # 停止 daemon
simtrade.py engine status    # 查看 daemon + cache 状态（JSON 输出）
simtrade.py engine restart   # = stop + start
```

### `engine start` 流程

```
1. 读 data/engine.pid（若存在）
2. 若 PID 文件存在：
   - 读 PID，检查进程是否存活（os.kill(pid, 0)，Windows 用 OpenProcess）
   - 进程活着 → 报错退出："daemon already running, PID=XXXX"
   - 进程已死 → 删除残留 PID 文件，继续启动（智能自愈）
3. subprocess.Popen([sys.executable, '-m', 'core.engine_daemon'],
                    stdout=append('data/engine.log'),
                    stderr=STDOUT,
                    stdin=DEVNULL,
                    start_new_session=True)  # detach
4. 写 PID 到 data/engine.pid
5. 等待最多 2 秒，确认 daemon 已写第一份 cache.json（否则报错："daemon failed to start, see data/engine.log"）
6. 输出 JSON：{"status": "started", "pid": XXXX, "cache_updated_at": "..."}
```

**步骤 5 是产品化关键**：避免"启动成功"但其实 daemon 立刻 crash。

### `engine stop` 流程

```
1. 读 data/engine.pid
2. 若不存在 → 报错："daemon not running (no PID file)"
3. 读 PID，检查进程是否存活
   - 已死 → 清理 PID 文件，输出："daemon was not running (stale PID cleaned)"
   - 活着 → 发 SIGTERM（Unix）/ taskkill /PID /T（Windows）
4. 等待最多 5 秒确认进程退出
5. 清理 PID 文件
6. 输出 JSON：{"status": "stopped"}
```

### `engine status` 输出

```json
{
  "daemon": "running" | "crashed" | "not_started",
  "pid": 12345,
  "cache": {
    "updated_at": "2026-06-13T14:30:15",
    "age_secs": 2,
    "fresh": true,
    "trading_active": false,
    "quotes_count": 8
  },
  "log_tail": ["...最后 5 行 data/engine.log..."]
}
```

### 跨平台信号处理

抽象成 `core/engine_ctl.py` 内部的辅助函数：
- Unix：`os.kill(pid, signal.SIGTERM)`
- Windows：`subprocess.run(['taskkill', '/PID', str(pid), '/T'])`

## CLI 改造（`simtrade.py` + `core/engine.py`）

### 受影响的命令

| 命令 | 现状 | 改造后 |
|---|---|---|
| `quote <code>` | `get_realtime_price` | 读 cache |
| `quotes <codes>` | `get_batch_realtime_prices` | 读 cache |
| `status` | engine.py 内调 `get_batch_realtime_prices` | 读 cache |
| `buy` / `sell` / `buy_market` / `sell_market` | engine.py 内调 `get_realtime_price` | 读 cache |
| `report` | 不调行情 | 不变 |
| `pnl` / `history` / `reset` / `init` | 不调行情 | 不变 |
| `watch` | CLI 轮询告警 | **删除**（被 watcher.py 取代） |

### `core/cache.py` 接口

```python
class CacheError(Exception): pass
class CacheStaleError(CacheError): pass
class CacheMissingError(CacheError): pass

def read_cache() -> dict:
    """读 cache.json，文件不存在抛 CacheMissingError"""

def age_secs(data: dict) -> float:
    """根据 updated_at 计算缓存年龄（秒）"""

def ensure_fresh(data: dict):
    """根据 trading_active + cache_ttl_multiplier 判断新鲜度，过期抛 CacheStaleError"""

def get_quote(code: str) -> dict:
    """读 cache 拿单只股票，过期/缺失抛 CacheError"""

def get_quotes(codes: list) -> dict:
    """批量读 cache，部分缺失时返回部分结果 + 缺失列表"""

def write_atomic(data: dict):
    """原子写 cache.json（先写 .tmp 再 rename），daemon 专用"""
```

### `core/engine.py` 改造

```python
# 改前
from core.market import get_realtime_price
price = get_realtime_price(code)

# 改后
from core.cache import get_quote
quote = get_quote(code)
price = quote['price']
```

**对外 API 不变**：`engine.buy(code, price, qty)` 等函数签名、返回值结构保持原样，CLI handler 业务逻辑不动。

### 错误传播

`simtrade.py` 的 `safe_execute` 捕获元组扩展：

```python
except (ValueError, RuntimeError, FileNotFoundError, CacheError) as e:
    json_error(str(e))
```

## watcher.py 改造

### `_refresh()` 主流程

```python
def _refresh(self):
    if not self._running:
        return
    try:
        data = cache.read_cache()
        cache_age = cache.age_secs(data)
        trading_active = data.get('trading_active', False)
        batch = data.get('quotes', {})
        self._prev_quotes = dict(self.quotes)
        self.quotes = batch
        self._cache_age = cache_age
        self._trading_active = trading_active
        self._update_labels()
        self._update_status_bar()
        # ... 策略检查、心跳等保留
    except CacheError as e:
        self._show_daemon_warning(str(e))

    # 节拍切换：非交易时段用 refresh_interval_off_hours
    interval = (config.refresh_interval if self._trading_active
                else config.refresh_interval_off_hours) * 1000
    self.root.after(interval, self._refresh)
```

### UI 状态条（顶部新增）

| 状态 | 触发条件 | 显示 |
|---|---|---|
| 正常 | `cache_age <= current_ttl` | "● 实时"（绿色）或不显示 |
| 轻微过期 | `current_ttl < cache_age <= cache_freshness_warn_secs` | "⚠ 缓存滞后 {N}s"（黄色） |
| 严重过期 | `cache_age > cache_freshness_warn_secs` | "⚠ daemon 未运行或异常（缓存 {N}s 未更新）"（红色） |
| cache 不存在 | `CacheMissingError` | "⚠ daemon 未启动，运行 `simtrade.py engine start`"（红色） |

### daemon 活性判断

**watcher 只看 cache.json 的 `updated_at`，不读 PID 文件。**
- daemon 写 cache 是它的"心跳"，cache 过期 = daemon 心跳停了
- 这覆盖"daemon 在跑但网络断了"的情况（cache 也会过期）
- 避免让 watcher 关心 daemon 的 PID，保持文件契约解耦

### 非交易时段行为

- watcher 读 cache 节拍跟随 daemon（交易时段 `refresh_interval`，非交易 `refresh_interval_off_hours`）
- **节拍判断依据**：watcher 从最新一次读到的 cache 里取 `trading_active` 字段决定下次 `root.after` 的 interval（daemon 已经算过 `is_trading_hours()`，watcher 不重复算，信任 cache）
- 读 `trading_active: false` 做 UI 灰显（价格文字变浅灰）
- **不停止刷新**（继承 `64991b9`：非交易时段仍显示收盘价）
- 首次启动时（cache 还没读到）默认用 `refresh_interval`，等第一次读到 cache 后按 `trading_active` 切换

## 测试策略

| 模块 | 测试方式 |
|---|---|
| `core/cache.py` | 单元测试（pytest）。覆盖：原子写、TTL 判断（交易/非交易）、错误类型 |
| `core/engine_ctl.py` | 集成测试。真实 subprocess 启动/停止/状态，验证 PID 文件生命周期 |
| `core/engine_daemon.py` | 集成测试。启动 daemon → 等待 cache 写入 → 验证内容 → 停止 |
| `simtrade.py` CLI 改造 | 端到端。`python simtrade.py quote sh600519` 验证 JSON 输出 |
| `watcher.py` | **手动验收为主**（tkinter 难自动化）。验证：状态条变化、节拍切换、灰显 |

**周六测试约束**：
- 腾讯 API 非交易时段返回上周五收盘数据，daemon 拉得到但价格不动
- 不影响 cache 读写、daemon 生命周期、错误处理的测试
- watcher 实时跳价的动态行为等交易日验证

## 边界与已知约束

- **`get_realtime_price` 在 `core/market.py` 仍保留**：作为 daemon 的实际请求层。其他模块不再直接调用它（除 daemon）
- **`fetch_with_fallback` 同理保留**：daemon 可选用它做更健壮的拉取
- **CLI 查询 watchlist 之外的股票会报错**：`CacheMissingError` 提示用户加进 watchlist 或 portfolio
- **同时启动多个 watcher 实例**：都读同一份 cache.json，无冲突（只读）
- **daemon 与 watcher 同时关闭再开**：cache.json 时间戳过期会触发 watcher UI 标注，用户看到后启动 daemon 即可
