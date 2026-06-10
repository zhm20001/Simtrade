#!/usr/bin/env python3
"""极简盯盘 — tkinter 置顶窗口，实时显示自选股行情"""

import json
import os
import platform
import subprocess
import sys
import time

import tkinter as tk
from tkinter import ttk, messagebox

# 确保能 import core
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core.config import ensure_data_dir, STRATEGY_PATH
from core.market import get_batch_realtime_prices, get_stock_name
from core.engine import load_strategy, check_rules

WATCHLIST_PATH = os.path.join(SCRIPT_DIR, 'data', 'watchlist.json')

DEFAULT_WATCHLIST = {
    'codes': [],
    'fields': {
        'volume': True,
        'high_low': True,
        'turnover': True,
        'amount': False,
    },
    'refresh_interval': 3,
    'font_size': 13,
    'window_width': 320,
    'window_height': None,
    'window_x': None,
    'window_y': None,
}

# A股配色
COLOR_UP = '#cf4444'
COLOR_DOWN = '#2ea043'
COLOR_FLAT = '#888888'
COLOR_BG = '#2b2b2b'
COLOR_BG_ROW = '#353535'
COLOR_FG = '#d4d4d4'
COLOR_DIM = '#808080'
COLOR_TITLE = '#3c3c3c'
COLOR_BTN = '#4a4a4a'
COLOR_BTN_FG = '#e0e0e0'
COLOR_ACCENT = '#0078d4'

# 通知防抖
_notify_timestamps = {}


def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 合并默认值
        result = dict(DEFAULT_WATCHLIST)
        result.update(data)
        if 'fields' in data:
            result['fields'] = dict(DEFAULT_WATCHLIST['fields'], **data['fields'])
        return result
    return dict(DEFAULT_WATCHLIST)


def save_watchlist(wl):
    ensure_data_dir()
    with open(WATCHLIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(wl, f, ensure_ascii=False, indent=2)


def format_volume(vol):
    if vol >= 100000000:
        return f'{vol/100000000:.1f}亿'
    if vol >= 10000:
        return f'{vol/10000:.1f}万'
    return f'{vol:.0f}'


def send_notification(title, message):
    """发送系统通知"""
    system = platform.system()
    try:
        if system == 'Darwin':
            subprocess.run([
                'osascript', '-e',
                f'display notification "{message}" with title "{title}"'
            ], timeout=5, capture_output=True)
        elif system == 'Windows':
            # Windows 使用 tkinter 弹窗（避免额外依赖）
            # 但在后台线程中不能操作 tkinter，所以用 ctypes
            try:
                from ctypes import windll
                windll.user32.MessageBoxTimeoutW(0, message, title, 0x40, 0, 3000)
            except Exception:
                pass
    except Exception:
        pass


def notify_triggered(triggered):
    """策略触发通知，带防抖"""
    global _notify_timestamps
    now = time.time()
    for t in triggered:
        key = f"{t['rule_name']}_{t['code']}"
        last = _notify_timestamps.get(key, 0)
        if now - last < 60:
            continue
        _notify_timestamps[key] = now
        title = f"策略触发: {t['rule_name']}"
        direction = '突破' if 'above' in t['type'] else '跌破'
        msg = f"{t['name']} {t['code']} 当前 {t['current_price']}，{direction}目标价"
        send_notification(title, msg)


class SettingsWindow:
    """设置窗口"""

    def __init__(self, parent, watcher_app):
        self.watcher = watcher_app
        self.win = tk.Toplevel(parent)
        self.win.title('设置')
        self.win.configure(bg=COLOR_BG)
        self.win.resizable(True, True)
        self.win.grab_set()
        self.win.attributes('-topmost', True)
        self.win.minsize(300, 400)

        wl = watcher_app.watchlist
        pad = {'padx': 12, 'pady': 4}
        entry_bg = '#404040'

        # === 自选股列表 ===
        tk.Label(self.win, text='自选股（最多10只）', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(anchor='w', **pad)

        list_frame = tk.Frame(self.win, bg=COLOR_BG)
        list_frame.pack(fill='x', **pad)

        self.stock_listbox = tk.Listbox(
            list_frame, height=6, bg=entry_bg, fg=COLOR_FG,
            selectbackground=COLOR_ACCENT, selectforeground='white',
            font=('Consolas', 11), relief='flat', highlightthickness=1,
            highlightbackground='#555555',
        )
        self.stock_listbox.pack(side='left', fill='x', expand=True)

        scrollbar = tk.Scrollbar(list_frame, command=self.stock_listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.stock_listbox.config(yscrollcommand=scrollbar.set)

        # 股票名称映射
        self.code_names = {}
        self._populate_list(wl['codes'])

        btn_frame = tk.Frame(self.win, bg=COLOR_BG)
        btn_frame.pack(fill='x', **pad)

        ttk.Button(btn_frame, text='移除选中', command=self._remove_stock,
                   style='Flat.TButton').pack(side='left')

        # 添加输入
        add_frame = tk.Frame(self.win, bg=COLOR_BG)
        add_frame.pack(fill='x', **pad)

        tk.Label(add_frame, text='添加:', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 10)).pack(side='left')
        self.add_entry = tk.Entry(add_frame, width=12, bg=entry_bg, fg=COLOR_FG,
                                  insertbackground=COLOR_FG, font=('Consolas', 11),
                                  relief='flat', highlightthickness=1,
                                  highlightbackground='#555555')
        self.add_entry.pack(side='left', padx=5)
        ttk.Button(add_frame, text='+', command=self._add_stock,
                   style='Accent.TButton').pack(side='left')

        # === 显示字段 ===
        tk.Label(self.win, text='显示字段', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(anchor='w', **pad)

        field_frame = tk.Frame(self.win, bg=COLOR_BG)
        field_frame.pack(fill='x', **pad)

        self.field_vars = {}
        fields = [('volume', '成交量'), ('high_low', '最高/最低'),
                  ('turnover', '换手率'), ('amount', '成交额')]
        for i, (key, label) in enumerate(fields):
            var = tk.BooleanVar(value=wl['fields'].get(key, False))
            self.field_vars[key] = var
            tk.Checkbutton(field_frame, text=label, variable=var,
                           bg=COLOR_BG, fg=COLOR_FG, selectcolor=entry_bg,
                           activebackground=COLOR_BG, activeforeground=COLOR_FG,
                           font=('Arial', 10)).grid(row=i//2, column=i%2, sticky='w')

        # === 数值设置 ===
        num_frame = tk.Frame(self.win, bg=COLOR_BG)
        num_frame.pack(fill='x', **pad)

        self.refresh_var = tk.IntVar(value=wl['refresh_interval'])
        self.font_var = tk.IntVar(value=wl['font_size'])
        self.width_var = tk.IntVar(value=wl['window_width'])
        self.auto_height_var = tk.BooleanVar(value=wl['window_height'] is None)
        self.height_var = tk.IntVar(value=wl['window_height'] or 400)

        nums = [
            ('刷新间隔(秒):', self.refresh_var, 1, 60),
            ('字体大小(px):', self.font_var, 8, 24),
            ('窗口宽度(px):', self.width_var, 200, 800),
        ]
        for i, (label, var, lo, hi) in enumerate(nums):
            tk.Label(num_frame, text=label, bg=COLOR_BG, fg=COLOR_FG,
                     font=('Arial', 10)).grid(row=i, column=0, sticky='w', pady=2)
            tk.Spinbox(num_frame, from_=lo, to=hi, textvariable=var, width=6,
                       bg=entry_bg, fg=COLOR_FG, font=('Consolas', 11),
                       relief='flat', insertbackground=COLOR_FG,
                       highlightthickness=1, highlightbackground='#555555'
                       ).grid(row=i, column=1, sticky='w', padx=5, pady=2)

        height_frame = tk.Frame(num_frame, bg=COLOR_BG)
        height_frame.grid(row=len(nums), column=0, columnspan=2, sticky='w', pady=2)
        tk.Checkbutton(height_frame, text='手动高度:', variable=self.auto_height_var,
                       bg=COLOR_BG, fg=COLOR_FG, selectcolor=entry_bg,
                       activebackground=COLOR_BG, activeforeground=COLOR_FG,
                       font=('Arial', 10)).pack(side='left')
        self.height_spin = tk.Spinbox(height_frame, from_=100, to=1200,
                                      textvariable=self.height_var, width=6,
                                      bg=entry_bg, fg=COLOR_FG, font=('Consolas', 11),
                                      relief='flat', insertbackground=COLOR_FG,
                                      highlightthickness=1, highlightbackground='#555555')
        self.height_spin.pack(side='left', padx=5)

        # === 保存/取消 ===
        action_frame = tk.Frame(self.win, bg=COLOR_BG)
        action_frame.pack(fill='x', **pad, pady=(8, 12))

        ttk.Button(action_frame, text='保存', command=self._save,
                   style='Accent.TButton').pack(side='left', expand=True)
        ttk.Button(action_frame, text='取消', command=self.win.destroy,
                   style='Flat.TButton').pack(side='left', expand=True)

    def _populate_list(self, codes):
        self.stock_listbox.delete(0, tk.END)
        self.code_names.clear()
        for code in codes:
            name = get_stock_name(code)
            self.code_names[code] = name
            self.stock_listbox.insert(tk.END, f'{code}  {name}')

    def _add_stock(self):
        code = self.add_entry.get().strip()
        if not code:
            return
        if len(self.code_names) >= 10:
            messagebox.showwarning('提示', '最多10只', parent=self.win)
            return
        if code in self.code_names:
            messagebox.showinfo('提示', '已存在', parent=self.win)
            return
        # 验证代码
        try:
            name = get_stock_name(code)
            if name == code:
                messagebox.showerror('错误', f'无法识别 {code}', parent=self.win)
                return
        except Exception:
            messagebox.showerror('错误', f'无法获取 {code} 行情', parent=self.win)
            return
        self.code_names[code] = name
        self.stock_listbox.insert(tk.END, f'{code}  {name}')
        self.add_entry.delete(0, tk.END)

    def _remove_stock(self):
        sel = self.stock_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        code = list(self.code_names.keys())[idx]
        del self.code_names[code]
        self.stock_listbox.delete(idx)

    def _save(self):
        codes = list(self.code_names.keys())
        fields = {k: v.get() for k, v in self.field_vars.items()}
        wl = {
            'codes': codes,
            'fields': fields,
            'refresh_interval': self.refresh_var.get(),
            'font_size': self.font_var.get(),
            'window_width': self.width_var.get(),
            'window_height': None if not self.auto_height_var.get() else self.height_var.get(),
        }
        save_watchlist(wl)
        self.watcher.watchlist = wl
        self.watcher.apply_settings()
        self.win.destroy()


class WatcherApp:
    """极简盯盘主应用"""

    def _setup_styles(self):
        """配置 ttk 样式（macOS 兼容）"""
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Toolbar.TButton', background=COLOR_BTN, foreground=COLOR_BTN_FG,
                         borderwidth=0, focusthickness=0, padding=(8, 4))
        style.map('Toolbar.TButton',
                   background=[('active', COLOR_ACCENT)],
                   foreground=[('active', 'white')])
        style.configure('Accent.TButton', background=COLOR_ACCENT, foreground='white',
                         borderwidth=0, focusthickness=0, padding=(20, 6))
        style.map('Accent.TButton',
                   background=[('active', '#005a9e')],
                   foreground=[('active', 'white')])
        style.configure('Flat.TButton', background=COLOR_BTN, foreground=COLOR_BTN_FG,
                         borderwidth=0, focusthickness=0, padding=(20, 6))
        style.map('Flat.TButton',
                   background=[('active', '#555555')],
                   foreground=[('active', 'white')])

    def __init__(self):
        self.watchlist = load_watchlist()
        self.quotes = {}
        self._prev_quotes = {}
        self._running = True
        self._resize_after_id = None

        # 主窗口 — 普通窗口（可缩放、Dock 可恢复）
        self.root = tk.Tk()
        self.root.title('极简盯盘')
        self.root.configure(bg=COLOR_BG)

        # 配置样式
        self._setup_styles()
        self.root.resizable(True, True)
        self.root.minsize(200, 100)

        # 置顶
        self.root.attributes('-topmost', True)

        # 窗口大小和位置
        self._apply_window_size()

        # 工具栏
        toolbar = tk.Frame(self.root, bg=COLOR_TITLE, height=32)
        toolbar.pack(fill='x')
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text=' 自选股行情', bg=COLOR_TITLE, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(side='left', padx=4)

        ttk.Button(toolbar, text='⚙ 设置', command=self._open_settings,
                   style='Toolbar.TButton').pack(side='right', padx=4, pady=3)

        # 内容区域（可滚动）
        self.content_frame = tk.Frame(self.root, bg=COLOR_BG)
        self.content_frame.pack(fill='both', expand=True)

        self.canvas = tk.Canvas(self.content_frame, bg=COLOR_BG, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.content_frame, orient='vertical',
                                      command=self.canvas.yview)
        self.scrollable = tk.Frame(self.canvas, bg=COLOR_BG)

        self.scrollable.bind('<Configure>',
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.create_window((0, 0), window=self.scrollable, anchor='nw')
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side='left', fill='both', expand=True)
        self.scrollbar.pack(side='right', fill='y')

        # 鼠标滚轮
        self.canvas.bind('<Enter>', lambda e: self.canvas.bind_all('<MouseWheel>', self._on_scroll))
        self.canvas.bind('<Leave>', lambda e: self.canvas.unbind_all('<MouseWheel>'))

        # 窗口大小变更保存
        self.root.bind('<Configure>', self._on_resize)

        # 系统托盘
        self._setup_tray()

        # 无自选股时自动弹出设置
        if not self.watchlist['codes']:
            self.root.after(500, self._open_settings)

        # 开始刷新
        self.root.after(100, self._refresh)

    def _apply_window_size(self):
        wl = self.watchlist
        w = wl.get('window_width', 320)
        h = wl.get('window_height')
        x = wl.get('window_x')
        y = wl.get('window_y')
        if h is None:
            n = max(len(wl.get('codes', [])), 1)
            row_h = self._estimate_row_height()
            h = 30 + n * row_h + 10
            h = min(h, 800)
        else:
            h = max(h, 100)
        geo = f'{w}x{h}'
        if x is not None and y is not None:
            geo += f'+{x}+{y}'
        self.root.geometry(geo)

    def _estimate_row_height(self):
        fs = self.watchlist.get('font_size', 13)
        base = int(fs * 2.5)
        fields = self.watchlist.get('fields', {})
        extra = sum(1 for k in ['high_low', 'turnover', 'amount'] if fields.get(k))
        extra += 1 if fields.get('volume') else 0
        return base + extra * int(fs * 1.4)

    def apply_settings(self):
        """设置保存后调用，重新渲染"""
        self._apply_window_size()
        self._render_quotes()

    def _on_scroll(self, event):
        if platform.system() == 'Darwin':
            self.canvas.yview_scroll(int(-1 * event.delta), 'units')
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _on_resize(self, event):
        if event.widget != self.root:
            return
        # 防抖：500ms 后才保存
        if self._resize_after_id:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(500, self._save_window_size)

    def _save_window_size(self):
        wl = self.watchlist
        wl['window_width'] = self.root.winfo_width()
        wl['window_x'] = self.root.winfo_x()
        wl['window_y'] = self.root.winfo_y()
        if wl.get('window_height') is not None:
            wl['window_height'] = self.root.winfo_height()
        save_watchlist(wl)

    def _open_settings(self):
        SettingsWindow(self.root, self)

    def _quit(self):
        self._running = False
        # 保存窗口位置
        try:
            save_watchlist(self.watchlist)
        except Exception:
            pass
        self.root.destroy()

    def _setup_tray(self):
        """系统托盘（简化版，使用 tkinter 菜单模拟）"""
        # macOS 菜单栏停靠
        # Windows 系统托盘需要 pystray，这里用简化方案：
        # 最小化后通过 Dock/任务栏图标恢复
        pass

    def _refresh(self):
        """定时刷新行情"""
        if not self._running:
            return
        codes = self.watchlist.get('codes', [])
        if codes:
            try:
                batch = get_batch_realtime_prices(codes)
                self._prev_quotes = dict(self.quotes)
                self.quotes = batch
                self._render_quotes()

                # 检查策略
                strategy = load_strategy()
                if strategy.get('rules'):
                    triggered = check_rules(strategy['rules'], batch)
                    if triggered:
                        notify_triggered(triggered)
            except Exception:
                # 网络错误：保留上次数据，下次重试
                pass

        interval = self.watchlist.get('refresh_interval', 3) * 1000
        self.root.after(interval, self._refresh)

    def _render_quotes(self):
        """渲染行情到界面"""
        for widget in self.scrollable.winfo_children():
            widget.destroy()

        codes = self.watchlist.get('codes', [])
        fs = self.watchlist.get('font_size', 13)
        fields = self.watchlist.get('fields', {})
        w = self.watchlist.get('window_width', 320) - 20

        if not codes:
            tk.Label(self.scrollable, text='暂无自选股\n点击 ⚙ 添加',
                     bg=COLOR_BG, fg=COLOR_DIM, font=('Arial', fs),
                     justify='center').pack(pady=30)
            return

        for code in codes:
            quote = self.quotes.get(code)
            if not quote:
                # 尚未获取到数据
                frame = tk.Frame(self.scrollable, bg=COLOR_BG_ROW)
                frame.pack(fill='x', padx=5, pady=2)
                tk.Label(frame, text=f'{code}  加载中...', bg=COLOR_BG_ROW,
                         fg=COLOR_DIM, font=('Consolas', fs), anchor='w'
                         ).pack(fill='x', padx=8, pady=4)
                continue

            price = quote.get('price', 0)
            name = quote.get('name', code)
            change = quote.get('change', 0)
            change_pct = quote.get('change_pct', 0)

            # 判断涨跌
            if change > 0:
                color = COLOR_UP
                arrow = '▲'
                sign = '+'
            elif change < 0:
                color = COLOR_DOWN
                arrow = '▼'
                sign = ''
            else:
                color = COLOR_FLAT
                arrow = '─'
                sign = ''

            # 是否有上次价格用于判断是否过期
            is_stale = code not in self.quotes and code in self._prev_quotes

            frame = tk.Frame(self.scrollable, bg=COLOR_BG_ROW)
            frame.pack(fill='x', padx=5, pady=2)

            # 第一行：名称 + 代码
            row1 = tk.Frame(frame, bg=COLOR_BG_ROW)
            row1.pack(fill='x', padx=8, pady=(6, 0))
            tk.Label(row1, text=name, bg=COLOR_BG_ROW, fg=COLOR_FG,
                     font=('Arial', fs, 'bold'), anchor='w').pack(side='left')
            tk.Label(row1, text=code, bg=COLOR_BG_ROW, fg=COLOR_DIM,
                     font=('Consolas', fs - 2), anchor='e').pack(side='right')

            # 第二行：价格 + 涨跌
            row2 = tk.Frame(frame, bg=COLOR_BG_ROW)
            row2.pack(fill='x', padx=8)
            price_fg = COLOR_DIM if is_stale else color
            tk.Label(row2, text=f'{price:.2f}', bg=COLOR_BG_ROW, fg=price_fg,
                     font=('Consolas', fs + 2, 'bold'), anchor='w').pack(side='left')
            tk.Label(row2, text=f'{arrow} {sign}{change:.2f} ({sign}{change_pct:.2f}%)',
                     bg=COLOR_BG_ROW, fg=price_fg,
                     font=('Consolas', fs), anchor='e').pack(side='right')

            # 可选字段行
            extra_parts = []
            if fields.get('volume') and quote.get('volume'):
                vol = quote['volume']
                extra_parts.append(f'量:{format_volume(vol)}手')
            if fields.get('amount') and quote.get('amount'):
                extra_parts.append(f'额:{format_volume(quote["amount"])}')

            if extra_parts:
                row3 = tk.Frame(frame, bg=COLOR_BG_ROW)
                row3.pack(fill='x', padx=8)
                tk.Label(row3, text='  '.join(extra_parts), bg=COLOR_BG_ROW,
                         fg=COLOR_DIM, font=('Consolas', fs - 2),
                         anchor='w').pack(fill='x')

            extra_parts2 = []
            if fields.get('high_low'):
                hi = quote.get('high', price)
                lo = quote.get('low', price)
                extra_parts2.append(f'高:{hi:.2f} 低:{lo:.2f}')
            if fields.get('turnover') and quote.get('turnover'):
                extra_parts2.append(f'换:{quote["turnover"]:.2f}%')

            if extra_parts2:
                row4 = tk.Frame(frame, bg=COLOR_BG_ROW)
                row4.pack(fill='x', padx=8, pady=(0, 6))
                tk.Label(row4, text='  '.join(extra_parts2), bg=COLOR_BG_ROW,
                         fg=COLOR_DIM, font=('Consolas', fs - 2),
                         anchor='w').pack(fill='x')

        # 分隔线（最后一条不需要）
        # 用 pady=2 的 frame gap 代替

    def run(self):
        self.root.mainloop()


def main():
    app = WatcherApp()
    app.run()


if __name__ == '__main__':
    main()
