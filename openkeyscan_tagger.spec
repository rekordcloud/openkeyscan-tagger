# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path

block_cipher = None

# Read target architecture from environment variable (set by build script)
# This ensures PyInstaller validates that the terminal arch matches the target
target_arch = os.environ.get('TARGET_ARCH', None)  # 'arm64', 'x86_64', or None (auto-detect)

# Determine the base path
base_path = Path.cwd()

# Data files to bundle
datas = []

# Hidden imports that PyInstaller might miss
hiddenimports = [
    'mutagen',
    'mutagen.id3',
    'mutagen.mp4',
    'mutagen.flac',
    'mutagen.oggvorbis',
    'mutagen.aiff',
    'mutagen.wave',
]

a = Analysis(
    ['openkeyscan_tagger.py'],
    pathex=[str(base_path)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe_server = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='openkeyscan-tagger',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=target_arch,  # Set from environment variable (arm64, x86_64, or None)
    codesign_identity='Developer ID Application: Rekordcloud B.V. (2B7KR8BSYR)',
    entitlements_file='./analyzer.entitlements',
)

coll = COLLECT(
    exe_server,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='openkeyscan-tagger',
)
