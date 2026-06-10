# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — macOS .app / Windows folder"""

import sys

a = Analysis(
    ['watcher.py'],
    pathex=[],
    binaries=[],
    datas=[('core', 'core'), ('data', 'data')],
    hiddenimports=['core', 'core.config', 'core.engine', 'core.market'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='极简盯盘',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='极简盯盘',
)

# macOS: 生成 .app 包
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='极简盯盘.app',
        icon='assets/icon.icns',
        bundle_identifier='com.simtrade.watcher',
        info_plist={
            'CFBundleShortVersionString': '0.7',
            'CFBundleName': '极简盯盘',
            'LSUIElement': False,
            'NSHighResolutionCapable': True,
        },
    )
