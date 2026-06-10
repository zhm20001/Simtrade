#!/usr/bin/env python3
"""极简盯盘 v0.5 — tkinter 置顶窗口，实时显示自选股行情"""

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
VERSION = '0.6'

DEFAULT_WATCHLIST = {
    'groups': [{'name': '默认', 'codes': []}],
    'active_group': 0,
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
    'opacity': 0.95,
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

# 通知状态：记录每条规则是否已触发（仅首次触发，条件解除后重置）
_triggered_state = {}  # key -> bool


def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        result = dict(DEFAULT_WATCHLIST)
        result.update(data)
        if 'fields' in data:
            result['fields'] = dict(DEFAULT_WATCHLIST['fields'], **data['fields'])
        # 兼容旧格式：codes → 默认分组
        if 'codes' in data and 'groups' not in data:
            result['groups'] = [{'name': '默认', 'codes': data['codes']}]
            result.pop('codes', None)
        if 'groups' not in result:
            result['groups'] = [{'name': '默认', 'codes': []}]
        if 'active_group' not in result:
            result['active_group'] = 0
        return result
    return dict(DEFAULT_WATCHLIST)


def get_active_codes(wl):
    """获取当前活动分组的股票代码列表"""
    groups = wl.get('groups', [])
    idx = wl.get('active_group', 0)
    if not groups:
        return []
    idx = min(idx, len(groups) - 1)
    return groups[idx].get('codes', [])


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
    system = platform.system()
    try:
        if system == 'Darwin':
            subprocess.run([
                'osascript', '-e',
                f'display notification "{message}" with title "{title}"'
            ], timeout=5, capture_output=True)
        elif system == 'Windows':
            try:
                from ctypes import windll
                windll.user32.MessageBoxTimeoutW(0, message, title, 0x40, 0, 3000)
            except Exception:
                pass
    except Exception:
        pass


def notify_triggered(triggered, all_rules, prices):
    """仅首次触发通知：条件满足时通知一次，持续满足不再通知；
    条件解除后再重新满足时才再次通知。"""
    global _triggered_state
    triggered_keys = set()
    for t in triggered:
        key = f"{t['rule_name']}_{t['code']}"
        triggered_keys.add(key)
        if not _triggered_state.get(key):
            title = f"策略触发: {t['rule_name']}"
            direction = '突破' if 'above' in t['type'] else '跌破'
            msg = f"{t['name']} {t['code']} 当前 {t['current_price']}，{direction}目标价"
            send_notification(title, msg)
        _triggered_state[key] = True
    # 条件解除的规则重置状态
    for rule in all_rules:
        key = f"{rule.get('name', '')}_{rule['code']}"
        if key not in triggered_keys:
            _triggered_state[key] = False


class SettingsWindow:
    """设置窗口"""

    def __init__(self, parent, watcher_app):
        self.watcher = watcher_app
        self.win = tk.Toplevel(parent)
        self.win.title(f'极简盯盘 v{VERSION}')
        self.win.configure(bg=COLOR_BG)
        self.win.geometry('340x640')
        self.win.resizable(True, True)
        self.win.grab_set()
        self.win.attributes('-topmost', True)
        self.win.minsize(300, 580)

        wl = watcher_app.watchlist
        pad = {'padx': 12, 'pady': 4}
        entry_bg = '#404040'

        # 版本号
        tk.Label(self.win, text=f'v{VERSION}', bg=COLOR_BG, fg=COLOR_DIM,
                 font=('Consolas', 9)).pack(anchor='e', padx=12, pady=(6, 0))

        # 用 Frame 分区：上方内容可滚动，下方按钮固定
        main_frame = tk.Frame(self.win, bg=COLOR_BG)
        main_frame.pack(fill='both', expand=True)

        # === 分组管理 ===
        group_header = tk.Frame(main_frame, bg=COLOR_BG)
        group_header.pack(fill='x', **pad)
        tk.Label(group_header, text='分组', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(side='left')

        # 分组选择下拉框
        self.groups = [dict(g) for g in wl.get('groups', [])]
        self.active_group_idx = wl.get('active_group', 0)
        group_names = [g['name'] for g in self.groups] + ['+ 新建分组']
        self.group_var = tk.StringVar(value=self.groups[self.active_group_idx]['name']
                                      if self.groups else '')
        self.group_combo = ttk.Combobox(group_header, values=group_names,
                                         textvariable=self.group_var, width=14,
                                         state='readonly')
        self.group_combo.pack(side='left', padx=5)
        self.group_combo.bind('<<ComboboxSelected>>', self._on_group_change)

        ttk.Button(group_header, text='删除分组', command=self._delete_group,
                   style='Flat.TButton').pack(side='right')

        # === 自选股列表 ===
        tk.Label(main_frame, text='自选股（最多10只）', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(anchor='w', **pad)

        list_frame = tk.Frame(main_frame, bg=COLOR_BG)
        list_frame.pack(fill='x', **pad)

        self.stock_listbox = tk.Listbox(
            list_frame, height=5, bg=entry_bg, fg=COLOR_FG,
            selectbackground=COLOR_ACCENT, selectforeground='white',
            font=('Consolas', 11), relief='flat', highlightthickness=1,
            highlightbackground='#555555',
        )
        self.stock_listbox.pack(side='left', fill='x', expand=True)

        scrollbar = tk.Scrollbar(list_frame, command=self.stock_listbox.yview)
        scrollbar.pack(side='right', fill='y')
        self.stock_listbox.config(yscrollcommand=scrollbar.set)

        self.code_names = {}
        self._populate_list(self._current_codes())

        btn_frame = tk.Frame(main_frame, bg=COLOR_BG)
        btn_frame.pack(fill='x', **pad)

        ttk.Button(btn_frame, text='移除选中', command=self._remove_stock,
                   style='Flat.TButton').pack(side='left')

        # 添加输入
        add_frame = tk.Frame(main_frame, bg=COLOR_BG)
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
        tk.Label(main_frame, text='显示字段', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(anchor='w', **pad)

        field_frame = tk.Frame(main_frame, bg=COLOR_BG)
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
        num_frame = tk.Frame(main_frame, bg=COLOR_BG)
        num_frame.pack(fill='x', **pad)

        self.refresh_var = tk.IntVar(value=wl['refresh_interval'])
        self.font_var = tk.IntVar(value=wl['font_size'])
        self.width_var = tk.IntVar(value=wl['window_width'])
        self.opacity_var = tk.DoubleVar(value=wl.get('opacity', 0.95))
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

        # 透明度滑块
        opacity_row = len(nums)
        tk.Label(num_frame, text='背景透明度:', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 10)).grid(row=opacity_row, column=0, sticky='w', pady=2)
        self.opacity_label = tk.Label(num_frame, text=f'{self.opacity_var.get():.0%}',
                                       bg=COLOR_BG, fg=COLOR_ACCENT, font=('Consolas', 10))
        self.opacity_label.grid(row=opacity_row, column=1, sticky='w', padx=5, pady=2)
        opacity_scale = tk.Scale(num_frame, from_=0.3, to=1.0, resolution=0.05,
                                  orient='horizontal', variable=self.opacity_var,
                                  bg=COLOR_BG, fg=COLOR_FG, troughcolor=entry_bg,
                                  highlightthickness=0, showvalue=False, length=120,
                                  command=lambda v: self.opacity_label.config(text=f'{float(v):.0%}'))
        opacity_scale.grid(row=opacity_row + 1, column=0, columnspan=2, sticky='w', padx=0, pady=0)

        height_frame = tk.Frame(num_frame, bg=COLOR_BG)
        height_frame.grid(row=opacity_row + 2, column=0, columnspan=2, sticky='w', pady=2)
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

        # === 保存/取消（固定底部）===
        action_frame = tk.Frame(self.win, bg=COLOR_BG)
        action_frame.pack(side='bottom', fill='x', padx=12, pady=(8, 12))

        ttk.Button(action_frame, text='保存', command=self._save,
                   style='Accent.TButton').pack(side='left', expand=True)
        ttk.Button(action_frame, text='取消', command=self.win.destroy,
                   style='Flat.TButton').pack(side='left', expand=True)

    def _current_codes(self):
        idx = self.active_group_idx
        if 0 <= idx < len(self.groups):
            return self.groups[idx].get('codes', [])
        return []

    def _sync_codes_to_group(self):
        """将当前 code_names 同步回 groups 中对应分组"""
        self.groups[self.active_group_idx]['codes'] = list(self.code_names.keys())

    def _on_group_change(self, event=None):
        selection = self.group_var.get()
        if selection == '+ 新建分组':
            self._add_group()
            return
        # 保存当前分组的 codes
        self._sync_codes_to_group()
        # 切换到新分组
        for i, g in enumerate(self.groups):
            if g['name'] == selection:
                self.active_group_idx = i
                break
        self._populate_list(self._current_codes())

    def _add_group(self):
        """新建分组"""
        # 弹出简单输入框
        dialog = tk.Toplevel(self.win)
        dialog.title('新建分组')
        dialog.configure(bg=COLOR_BG)
        dialog.geometry('280x100')
        dialog.grab_set()
        dialog.attributes('-topmost', True)

        tk.Label(dialog, text='分组名称:', bg=COLOR_BG, fg=COLOR_FG,
                 font=('Arial', 11)).pack(pady=(12, 4))
        name_entry = tk.Entry(dialog, width=20, bg='#404040', fg=COLOR_FG,
                              insertbackground=COLOR_FG, font=('Consolas', 11),
                              relief='flat', highlightthickness=1,
                              highlightbackground='#555555')
        name_entry.pack(pady=4)
        name_entry.focus_set()

        def confirm(e=None):
            name = name_entry.get().strip()
            if not name:
                return
            # 检查重名
            for g in self.groups:
                if g['name'] == name:
                    messagebox.showinfo('提示', '分组名已存在', parent=dialog)
                    return
            self._sync_codes_to_group()
            self.groups.append({'name': name, 'codes': []})
            self.active_group_idx = len(self.groups) - 1
            self._refresh_group_combo()
            self._populate_list([])
            dialog.destroy()

        name_entry.bind('<Return>', confirm)
        ttk.Button(dialog, text='确定', command=confirm,
                   style='Accent.TButton').pack(pady=6)

    def _delete_group(self):
        if len(self.groups) <= 1:
            messagebox.showinfo('提示', '至少保留一个分组', parent=self.win)
            return
        name = self.groups[self.active_group_idx]['name']
        if not messagebox.askyesno('确认', f'删除分组 "{name}"？\n其中的股票不会影响其他分组。',
                                    parent=self.win):
            return
        self.groups.pop(self.active_group_idx)
        self.active_group_idx = min(self.active_group_idx, len(self.groups) - 1)
        self._refresh_group_combo()
        self._populate_list(self._current_codes())

    def _refresh_group_combo(self):
        group_names = [g['name'] for g in self.groups] + ['+ 新建分组']
        self.group_combo.config(values=group_names)
        self.group_var.set(self.groups[self.active_group_idx]['name'])

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
        self._sync_codes_to_group()
        fields = {k: v.get() for k, v in self.field_vars.items()}
        wl = {
            'groups': self.groups,
            'active_group': self.active_group_idx,
            'fields': fields,
            'refresh_interval': self.refresh_var.get(),
            'font_size': self.font_var.get(),
            'window_width': self.width_var.get(),
            'window_height': None if not self.auto_height_var.get() else self.height_var.get(),
            'opacity': round(self.opacity_var.get(), 2),
        }
        save_watchlist(wl)
        self.watcher.watchlist = wl
        self.watcher.apply_settings()
        self.win.destroy()


class WatcherApp:
    """极简盯盘主应用"""

    def _setup_styles(self):
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
        # 缓存已创建的控件，避免重建导致闪烁
        self._stock_widgets = {}  # code -> {row1_name, row1_code, row2_price, row2_change, row3, row4}

        self.root = tk.Tk()
        self.root.title(f'极简盯盘 v{VERSION}')
        self.root.configure(bg=COLOR_BG)

        self._setup_styles()
        self.root.resizable(True, True)
        self.root.minsize(200, 100)
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', self.watchlist.get('opacity', 0.95))

        self._apply_window_size()

        # 工具栏
        toolbar = tk.Frame(self.root, bg=COLOR_TITLE, height=32)
        toolbar.pack(fill='x')
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text=f' 自选股行情 v{VERSION}', bg=COLOR_TITLE, fg=COLOR_FG,
                 font=('Arial', 11, 'bold')).pack(side='left', padx=4)

        groups = self.watchlist.get('groups', [])
        idx = self.watchlist.get('active_group', 0)
        group_name = groups[idx]['name'] if groups and idx < len(groups) else ''
        if group_name and group_name != '默认':
            tk.Label(toolbar, text=group_name, bg=COLOR_TITLE, fg=COLOR_ACCENT,
                     font=('Arial', 10)).pack(side='left', padx=4)

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

        self.root.bind('<Configure>', self._on_resize)

        if not get_active_codes(self.watchlist):
            self.root.after(500, self._open_settings)

        self.root.after(100, self._refresh)

    def _apply_window_size(self):
        wl = self.watchlist
        w = wl.get('window_width', 320)
        h = wl.get('window_height')
        x = wl.get('window_x')
        y = wl.get('window_y')
        if h is None:
            n = max(len(get_active_codes(wl)), 1)
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
        self._apply_window_size()
        self.root.attributes('-alpha', self.watchlist.get('opacity', 0.95))
        # 股票列表变化时需要重建控件
        self._stock_widgets.clear()
        self._rebuild_layout()

    def _on_scroll(self, event):
        if platform.system() == 'Darwin':
            self.canvas.yview_scroll(int(-1 * event.delta), 'units')
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), 'units')

    def _on_resize(self, event):
        if event.widget != self.root:
            return
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
        try:
            save_watchlist(self.watchlist)
        except Exception:
            pass
        self.root.destroy()

    def _rebuild_layout(self):
        """重建整个布局（仅股票列表变化时调用）"""
        for widget in self.scrollable.winfo_children():
            widget.destroy()
        self._stock_widgets.clear()

        codes = get_active_codes(self.watchlist)
        fs = self.watchlist.get('font_size', 13)

        if not codes:
            tk.Label(self.scrollable, text='暂无自选股\n点击 ⚙ 添加',
                     bg=COLOR_BG, fg=COLOR_DIM, font=('Arial', fs),
                     justify='center').pack(pady=30)
            return

        for code in codes:
            frame = tk.Frame(self.scrollable, bg=COLOR_BG_ROW)
            frame.pack(fill='x', padx=5, pady=2)

            row1 = tk.Frame(frame, bg=COLOR_BG_ROW)
            row1.pack(fill='x', padx=8, pady=(6, 0))
            lbl_name = tk.Label(row1, text='', bg=COLOR_BG_ROW, fg=COLOR_FG,
                                font=('Arial', fs, 'bold'), anchor='w')
            lbl_name.pack(side='left')
            lbl_code = tk.Label(row1, text=code, bg=COLOR_BG_ROW, fg=COLOR_DIM,
                                font=('Consolas', fs - 2), anchor='e')
            lbl_code.pack(side='right')

            row2 = tk.Frame(frame, bg=COLOR_BG_ROW)
            row2.pack(fill='x', padx=8)
            lbl_price = tk.Label(row2, text='', bg=COLOR_BG_ROW, fg=COLOR_FLAT,
                                 font=('Consolas', fs + 2, 'bold'), anchor='w')
            lbl_price.pack(side='left')
            lbl_change = tk.Label(row2, text='', bg=COLOR_BG_ROW, fg=COLOR_FLAT,
                                  font=('Consolas', fs), anchor='e')
            lbl_change.pack(side='right')

            # 第三行：量/额
            row3 = tk.Frame(frame, bg=COLOR_BG_ROW)
            row3.pack(fill='x', padx=8)
            lbl_extra1 = tk.Label(row3, text='', bg=COLOR_BG_ROW, fg=COLOR_DIM,
                                  font=('Consolas', fs - 2), anchor='w')
            lbl_extra1.pack(fill='x')

            # 第四行：高/低/换
            row4 = tk.Frame(frame, bg=COLOR_BG_ROW)
            row4.pack(fill='x', padx=8, pady=(0, 6))
            lbl_extra2 = tk.Label(row4, text='', bg=COLOR_BG_ROW, fg=COLOR_DIM,
                                  font=('Consolas', fs - 2), anchor='w')
            lbl_extra2.pack(fill='x')

            self._stock_widgets[code] = {
                'frame': frame,
                'name': lbl_name,
                'code': lbl_code,
                'price': lbl_price,
                'change': lbl_change,
                'extra1': lbl_extra1,
                'extra2': lbl_extra2,
            }

    def _refresh(self):
        if not self._running:
            return
        codes = get_active_codes(self.watchlist)
        if codes:
            try:
                batch = get_batch_realtime_prices(codes)
                self._prev_quotes = dict(self.quotes)
                self.quotes = batch
                self._update_labels()

                strategy = load_strategy()
                if strategy.get('rules'):
                    triggered = check_rules(strategy['rules'], batch)
                    if triggered:
                        notify_triggered(triggered, strategy['rules'], batch)
            except Exception:
                pass

        interval = self.watchlist.get('refresh_interval', 3) * 1000
        self.root.after(interval, self._refresh)

    def _update_labels(self):
        """只更新文字和颜色，不销毁控件 — 消除闪烁"""
        codes = get_active_codes(self.watchlist)
        fields = self.watchlist.get('fields', {})
        fs = self.watchlist.get('font_size', 13)

        # 如果股票列表变化了（或首次），重建布局
        current_codes = set(self._stock_widgets.keys())
        if current_codes != set(codes):
            self._rebuild_layout()

        for code in codes:
            w = self._stock_widgets.get(code)
            if not w:
                continue

            quote = self.quotes.get(code)
            if not quote:
                w['name'].config(text=f'{code} 加载中...')
                w['price'].config(text='')
                w['change'].config(text='')
                w['extra1'].config(text='')
                w['extra2'].config(text='')
                continue

            price = quote.get('price', 0)
            name = quote.get('name', code)
            change = quote.get('change', 0)
            change_pct = quote.get('change_pct', 0)

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

            w['name'].config(text=name)
            w['price'].config(text=f'{price:.2f}', fg=color)
            w['change'].config(text=f'{arrow} {sign}{change:.2f} ({sign}{change_pct:.2f}%)', fg=color)

            # 可选字段
            extra1_parts = []
            if fields.get('volume') and quote.get('volume'):
                extra1_parts.append(f'量:{format_volume(quote["volume"])}手')
            if fields.get('amount') and quote.get('amount'):
                extra1_parts.append(f'额:{format_volume(quote["amount"])}')
            w['extra1'].config(text='  '.join(extra1_parts))

            extra2_parts = []
            if fields.get('high_low'):
                extra2_parts.append(f'高:{quote.get("high", price):.2f} 低:{quote.get("low", price):.2f}')
            if fields.get('turnover') and quote.get('turnover'):
                extra2_parts.append(f'换:{quote["turnover"]:.2f}%')
            w['extra2'].config(text='  '.join(extra2_parts))

    def run(self):
        self.root.mainloop()


def main():
    app = WatcherApp()
    app.run()


if __name__ == '__main__':
    main()
