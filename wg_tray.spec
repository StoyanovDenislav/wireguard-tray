# PyInstaller spec shared across macOS, Linux, and Windows.
# Build with: pyinstaller wg_tray.spec
import sys

from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# certifi's CA bundle is a data file, not code — PyInstaller's default
# import analysis won't pick it up on its own, and without it the
# updater's HTTPS requests fail certificate verification in frozen
# builds (see wgtray/updater.py's _ssl_context).
datas = [("wgtray/resources", "wgtray/resources")]
datas += collect_data_files("certifi")

a = Analysis(
    ["wg_tray.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["pyzbar.pyzbar", "certifi", "cryptography.hazmat.backends.openssl"],
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
