# -*- mode: python ; coding: utf-8 -*-
# Build flow (bakes your tested config.json into the exe so it runs standalone):
#   pip install -r requirements.txt
#   pyinstaller pipipupu.spec
# Output: dist/pipipupu.exe (single file, tesseract/ + baked config bundled)
# NOTE: the exe will contain your API keys — don't share the file publicly.
# config.json is gitignored, so a fresh clone builds with template defaults only.

import os

_datas = [
    ('tesseract', 'tesseract'),
    ('config.example.json', '.'),
]
# Bake the real tested config when building where it exists
if os.path.exists('config.json'):
    _datas.append(('config.json', '.'))

a = Analysis(
    ['pipipupu.py'],
    pathex=[],
    binaries=[],
    datas=_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pipipupu',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
