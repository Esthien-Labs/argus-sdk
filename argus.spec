# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification for the Argus SDK standalone CLI.
# Build this specification on the target operating system and architecture.
# It produces one executable for installation through the Windows application
# installer. The executable is not represented as source-code protection.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)
SOURCE_ROOT = ROOT / 'src'

a = Analysis(
    [str(SOURCE_ROOT / 'argus_release_cli.py')],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=collect_data_files('argus.resources'),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'IPython',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='argus',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
