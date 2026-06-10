# SimTrade

A股模拟交易系统 — CLI 交易引擎 + 极简盯盘工具。

## 功能

**CLI 交易系统**（`simtrade.py`）
- 15 个命令：初始化、买卖、持仓、盈亏、复盘、行情监控、策略、配置
- JSON 输出，供 LLM 自动化交易或程序化调用
- 模拟真实 A 股费用：万三佣金（最低 5 元）+ 千一印花税（卖出）

**极简盯盘工具**（`watcher.py`）
- tkinter 置顶窗口，实时显示自选股行情
- 涨红跌绿，支持分组切换、持仓浮盈联动、策略通知
- 非交易时段自动暂停刷新

## 快速开始

```bash
cd ~/simtrade

# 初始化账户
python simtrade.py init --cash 1000000

# 查看行情
python simtrade.py quotes sh600519,sz000858,sh600900

# 市价买入
python simtrade.py buy_market sh600519 100 --force --reason "分析理由"

# 启动盯盘
python watcher.py
```

## 依赖

- Python 3.10+
- pandas, requests（`pip install pandas requests`）
- tkinter（Python 内置）
- 无其他额外依赖

## 项目结构

```
simtrade/
  simtrade.py          CLI 入口（383 行）
  watcher.py           极简盯盘 UI（900 行）
  core/
    engine.py          交易引擎
    market.py          行情服务（腾讯/新浪 API）
    config.py          配置管理
  data/                 运行时数据（gitignore）
  assets/               图标
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

- [GUIDE.md](GUIDE.md) — 完整操作指南

## 许可

MIT
