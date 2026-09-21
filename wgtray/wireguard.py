"""Bringing tunnels up/down, and importing configs (.conf file or QR image)."""
import os
from pathlib import Path

from . import leak_protection
from .paths import CONFIGS_DIR
from .platform_utils import (
    IS_MAC, IS_WINDOWS, disconnect_other_vpn, find_bash, find_conflicting_vpn_interface,
    find_running_vpn_daemons, find_wg_quick, find_wireguard_exe, run_privileged,
)
from .state import config_path, leak_protection_enabled, load_state, save_state


def check_for_conflicting_vpn():
    """
    wg-tray (via wg-quick) only manages a single tunnel and doesn't
    coordinate with other VPN clients. If another VPN already holds the
    default route, wg-quick's own route setup breaks in confusing ways
    (see find_conflicting_vpn_interface's docstring) — this lets the
    caller warn about that *before* attempting to connect, instead of
    surfacing wg-quick's raw script failure after the fact.

    Returns None if no conflict is detected, otherwise a dict:
    {'interface': the conflicting utun/tun device name,
     'daemons': [(process_name, friendly_name), ...] of any recognized
                VPN daemons currently running (possibly unrelated to the
                actual conflict — just what's available to offer
                disconnecting, named so the user can judge for themselves)}
    """
    interface = find_conflicting_vpn_interface()
    if interface is None:
        return None
    return {"interface": interface, "daemons": find_running_vpn_daemons()}


def _effective_config_path(name):
    """
    The config wg-quick should actually use for this tunnel: the derived
    leak-protection copy if the user has enabled it for this tunnel and
    it's supported on this platform (macOS or Linux; see
    leak_protection.is_supported()), otherwise the original as-imported
    .conf. Regenerated fresh on every connect so edits to the original or
    a changed endpoint port are always picked up. Must be used
    consistently for both up and down — wg-quick derives the interface
    name from the config filename, so bringing it up via one path and
    down via another leaves it stuck.
    """
    if leak_protection.is_supported() and leak_protection_enabled(name):
        return leak_protection.generate_protected_config(name)
    return config_path(name)


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
        conf = str(_effective_config_path(name))
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
        # Use the *existing* derived config rather than regenerating it,
        # in case leak protection was toggled off while connected — we
        # still need to tear down via the same interface it came up on.
        if leak_protection.is_supported() and leak_protection.protected_config_path(name).exists():
            conf = str(leak_protection.protected_config_path(name))
        else:
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
