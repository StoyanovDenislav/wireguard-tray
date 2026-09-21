# PyInstaller spec shared across macOS, Linux, and Windows.
# Build with: pyinstaller wg_tray.spec
import sys

block_cipher = None

a = Analysis(
    ["wg_tray.py"],
    pathex=[],
    binaries=[],
    datas=[("wgtray/resources", "wgtray/resources")],
    hiddenimports=["pyzbar.pyzbar"],
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
    name="wg-tray",
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
    name="wg-tray",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="wg-tray.app",
        icon=None,
        bundle_identifier="dev.wgtray.app",
        info_plist={
            "CFBundleName": "wg-tray",
            "CFBundleDisplayName": "wg-tray",
            "LSUIElement": True,  # menu-bar-only app, no Dock icon
            "NSHighResolutionCapable": True,
        },
    )
