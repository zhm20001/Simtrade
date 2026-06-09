# 极简盯盘工具 (watcher.py) 设计文档

**状态：已批准**

## 目标

一个轻量级 tkinter 置顶窗口工具，实时显示自选股行情，支持策略触发通知。macOS/Windows 双平台，零额外依赖。

## 架构

```
~/simtrade/
  watcher.py           # 极简盯盘主程序（单文件）
  core/market.py        # 复用现有行情服务
  data/watchlist.json   # 自选股列表 + 显示偏好
  data/strategy.json    # 策略规则（已有）
```

数据流：`watchlist.json → watcher.py → core/market.py → 腾讯API → 屏幕渲染`

## 主窗口

- 无边框置顶，默认宽 320px，高度自动（每只约 30px + 可选字段行）
- 标题栏：齿轮图标（设置）+ 最小化 + 关闭
- 标题栏区域支持鼠标拖拽
- 窗口边缘可拖拽调整大小，松手自动保存
- A股配色：涨红（`#ff4444`）跌绿（`#00cc00`）平盘灰
- 等宽字体（Consolas/Monaco）

每只股票显示：
```
华能国际  sh600011
8.46  ▲ +0.06 (+0.71%)      ← 涨绿跌红（A股习惯）
量:1.2万手  高:8.52 低:8.38  ← 可选字段行
换:0.85%                     ← 可选字段行
```

## 设置窗口

点击齿轮图标弹出，约 320x450px：

- 自选股列表（最多10只），可逐个删除
- 添加：输入代码（如 sh600519），自动获取名称
- 保存时验证代码有效性
- 显示字段复选框：成交量、最高/最低、换手率、成交额
- 刷新间隔（秒，最小1）
- 字体大小（px）
- 窗口宽度
- 窗口高度（自动 / 手动，手动时超出滚动）
- 保存后热更新主窗口

## watchlist.json 结构

```json
{
  "codes": ["sh600011", "sh600900", "sh600795", "sh601985"],
  "fields": {
    "volume": true,
    "high_low": true,
    "turnover": true,
    "amount": false
  },
  "refresh_interval": 3,
  "font_size": 13,
  "window_width": 320,
  "window_height": null
}
```

## 策略通知

- 每次刷新后用 `core/engine.check_rules()` 检查策略
- 触发时发送系统通知：
  - macOS: `osascript -e 'display notification ...'`
  - Windows: tkinter `showinfo` 或 ctypes
- 同一条策略 60 秒内不重复通知（防抖）
- 通知内容：`"[止损] 华能国际 sh600011 当前 8.46，跌破 10.00"`

## 窗口行为

- 启动：`python watcher.py`，无自选股时自动弹出设置
- 最小化：关闭按钮最小化到系统托盘
- 托盘操作：左键恢复，右键菜单（显示/隐藏/设置/退出）
- 网络错误：显示上次价格，文字变灰，不弹窗

## 技术约束

- 单文件 watcher.py
- 只依赖 tkinter（Python 内置）+ core/ 模块
- macOS + Windows 双平台
- 无额外 pip 依赖
