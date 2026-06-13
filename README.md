# SimTrade

A股模拟交易系统 — CLI 交易引擎 + 极简盯盘工具。

## 功能

**CLI 交易系统**（`simtrade.py`）
- 15 个命令：初始化、买卖、持仓、盈亏、复盘、行情、策略、engine、配置
- JSON 输出，供 LLM 自动化交易或程序化调用
- 模拟真实 A 股费用：万三佣金（最低 5 元）+ 千一印花税（卖出）

**极简盯盘工具**（`watcher.py`）
- tkinter 置顶窗口，实时显示自选股行情
- 涨红跌绿，支持分组切换、持仓浮盈联动、策略通知
- 顶部状态栏显示缓存新鲜度和 daemon 健康状态

**本地数据 engine**（`simtrade.py engine`）
- 常驻 daemon 进程，统一抓取行情写入本地缓存
- CLI 与 watcher 共享缓存，外部请求减半
- 交易时段 3 秒刷新，非交易时段 60 秒

## 快速开始

```bash
cd ~/simtrade

# 1. 初始化账户（首次）
python simtrade.py init --cash 1000000

# 2. 启动本地数据 engine（daemon，交易时段每 3 秒抓行情）
python simtrade.py engine start

# 3. 查看行情（从本地缓存读，无外部请求）
python simtrade.py quotes sh600519,sz000858,sh600900

# 4. 市价买入
python simtrade.py buy_market sh600519 100 --force --reason "分析理由"

# 5. 启动盯盘
python watcher.py
```

> watcher 不会自动启动 daemon。如果不先 `engine start`，watcher 顶部状态栏会显示红色警告，行情为空。

## 依赖

- Python 3.10+
- pandas, requests（`pip install pandas requests`）
- tkinter（Python 内置）
- 无其他额外依赖

## 项目结构

```
simtrade/
  simtrade.py              CLI 入口
  watcher.py               极简盯盘 UI
  core/
    engine.py              交易引擎
    market.py              行情服务（腾讯/新浪 API）
    cache.py               本地缓存读写
    engine_ctl.py          daemon 进程管理（start/stop/status）
    engine_daemon.py       daemon 主循环
    config.py              配置管理
  data/                    运行时数据（gitignore）
  assets/                  图标
```

## 打包

macOS:
```bash
pip install pyinstaller
pyinstaller watcher.spec
# 产物: dist/极简盯盘.app
```

Windows 需在 Windows 环境下运行 `pyinstaller watcher.spec`。

## 文档

- [GUIDE.md](GUIDE.md) — 完整操作指南（含 engine daemon 详解）

## 许可

MIT
