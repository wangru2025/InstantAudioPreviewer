# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['InstantAudioPreviewer.py'],
    pathex=['.'],
    binaries=[('ZDSRAPI_x64.dll', '.'), ('SDL2_mixer.dll', '.'), ('SDL2.dll', '.'), ('nvdaControllerClient.dll', '.'), ('libxmp.dll', '.'), ('libwavpack-1.dll', '.'), ('libopusfile-0.dll', '.'), ('libopus-0.dll', '.'), ('libogg-0.dll', '.'), ('libgme.dll', '.')],
    datas=[],
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
    [],
    exclude_binaries=True,
    name='InstantAudioPreviewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='InstantAudioPreviewer',
)
