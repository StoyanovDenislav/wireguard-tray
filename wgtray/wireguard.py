"""Bringing tunnels up/down, and importing configs (.conf file or QR image)."""
import os
from pathlib import Path

from .paths import CONFIGS_DIR
from .platform_utils import (
    IS_MAC, IS_WINDOWS, find_bash, find_wg_quick, find_wireguard_exe, run_privileged,
)
from .state import config_path, load_state, save_state

try:
    from pyzbar.pyzbar import decode as qr_decode
    from PIL import Image
    HAVE_QR = True
except ImportError:
    HAVE_QR = False


def connect(name):
    if IS_WINDOWS:
        wireguard = find_wireguard_exe()
        if not wireguard:
            return False, "wireguard.exe not found. Install WireGuard for Windows first."
        conf = str(config_path(name))
        argv = [wireguard, "/installtunnelservice", conf]
    else:
        wg_quick = find_wg_quick()
        if not wg_quick:
            return False, "wg-quick not found. Install wireguard-tools first."
        conf = str(config_path(name))
        if IS_MAC:
            bash = find_bash()
            argv = [bash, wg_quick, "up", conf]
        else:
            argv = [wg_quick, "up", conf]

    ok, out = run_privileged(argv)
    if ok:
        state = load_state()
        state["active"] = name
        save_state(state)
    return ok, out


def disconnect(name):
    if IS_WINDOWS:
        wireguard = find_wireguard_exe()
        if not wireguard:
            return False, "wireguard.exe not found."
        # WireGuard for Windows names the service after the tunnel (config
        # stem), not the config path — unlike /installtunnelservice.
        argv = [wireguard, "/uninstalltunnelservice", name]
    else:
        wg_quick = find_wg_quick()
        if not wg_quick:
            return False, "wg-quick not found."
        conf = str(config_path(name))
        if IS_MAC:
            bash = find_bash()
            argv = [bash, wg_quick, "down", conf]
        else:
            argv = [wg_quick, "down", conf]

    ok, out = run_privileged(argv)
    if ok:
        state = load_state()
        if state.get("active") == name:
            state["active"] = None
        save_state(state)
    return ok, out


def import_conf_file(src_path, name):
    dest = config_path(name)
    if dest.exists():
        raise FileExistsError(f"A tunnel named '{name}' already exists.")
    dest.write_text(Path(src_path).read_text())
    os.chmod(dest, 0o600)


def import_from_qr_image(image_path, name):
    if not HAVE_QR:
        raise RuntimeError(
            "QR decoding needs pyzbar + Pillow. Install with:\n"
            "  pip install pyzbar pillow\n"
            "and the zbar system library (brew install zbar / pacman -S zbar)."
        )
    img = Image.open(image_path)
    results = qr_decode(img)
    if not results:
        raise ValueError("No QR code found in that image.")
    payload = results[0].data.decode("utf-8")
    if "[Interface]" not in payload:
        raise ValueError("QR code didn't contain a WireGuard config.")
    dest = config_path(name)
    if dest.exists():
        raise FileExistsError(f"A tunnel named '{name}' already exists.")
    dest.write_text(payload)
    os.chmod(dest, 0o600)
