# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for AI翻译输入法

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT = Path(SPECPATH)

# 收集所有需要的模块
all_datas = []
all_binaries = []
all_hiddenimports = []

for pkg in ['pyperclip', 'keyboard', 'pyautogui', 'qframelesswindow']:
    try:
        d, b, h = collect_all(pkg)
        all_datas += d
        all_binaries += b
        all_hiddenimports += h
    except Exception as e:
        print(f"Warning: Could not collect {pkg}: {e}")

a = Analysis(
    ['main.py'],
    pathex=[str(ROOT)],
    binaries=all_binaries,
    datas=all_datas,
    hiddenimports=all_hiddenimports + [
        'win32gui',
        'win32con',
        'win32api',
        'win32process',
        'PyQt6.sip',
        'certifi',
        'charset_normalizer',
        'idna',
        'urllib3',
        'requests',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI翻译输入法',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico' if (ROOT / 'app.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI翻译输入法',
)
