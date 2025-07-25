# -*- mode: python ; coding: utf-8 -*-

VLC_PATH = 'C:\\Program Files\\VideoLAN\\VLC'

a = Analysis(
    ['InstantAudioPreviewer.py'],
    pathex=[],
    binaries=[('libvlc.dll', '.'), ('libvlccore.dll', '.'), ('nvdaControllerClient.dll', '.'), ('ZDSRAPI_x64.dll', '.')],
    datas=[
        # --- VLC Runtime Files ---
        (f'{VLC_PATH}\\libvlc.dll', '.'), # 确保 libvlc.dll 也被包含
        (f'{VLC_PATH}\\libvlccore.dll', '.'), # 确保 libvlccore.dll 也被包含
        (f'{VLC_PATH}\\plugins', 'plugins'), # 包含 VLC 的插件目录，非常重要！
        # 根据你的程序需求，可能还需要包含 VLC 的其他资源文件，例如：
        # (f'{VLC_PATH}\\vlc.exe', 'vlc.exe'), # 如果你的代码直接调用 vlc.exe
        # (f'{VLC_PATH}\\vlc.ico', '.'),
        # (f'{VLC_PATH}\\playlist.xml', '.'),
    ],
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