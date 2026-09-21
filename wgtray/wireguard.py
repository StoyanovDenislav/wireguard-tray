"""Bringing tunnels up/down, and importing configs (.conf file or QR image)."""
import os
import re
from pathlib import Path

from . import key_encryption, leak_protection
from .paths import CONFIGS_DIR, RUNTIME_DIR
from .platform_utils import (
    IS_MAC, IS_WINDOWS, disconnect_other_vpn, find_bash, find_conflicting_vpn_interface,
    find_running_vpn_daemons, find_wg_quick, find_wireguard_exe, run_privileged,
)
from .state import config_path, leak_protection_enabled, load_state, save_state


class PassphraseRequired(Exception):
    """Raised by connect() when the tunnel's PrivateKey is encrypted and
    no decrypted_private_key was supplied — the caller (on the main
    thread, since this needs a Qt prompt) should ask the user for the
    passphrase, decrypt it themselves (key_encryption.decrypt_key), and
    call connect() again passing the result."""


def _write_private(path, text):
    """Write text to path with 0600 permissions from the moment the file
    exists, rather than write-then-chmod — the latter leaves a brief
    window where a private key sits in a file with default,
    umask-dependent (potentially world-readable) permissions."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def is_encrypted(name):
    return key_encryption.is_encrypted(config_path(name).read_text())


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


def _effective_config_path(name, decrypted_private_key=None):
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

    If the tunnel's PrivateKey is encrypted, decrypted_private_key must
    be supplied (see connect()'s PassphraseRequired) — the returned path
    then points at a plaintext temp copy in RUNTIME_DIR (never
    CONFIGS_DIR) with the same basename wg-quick would have used
    otherwise, so the interface name it derives still matches between up
    and down. Caller is responsible for deleting that temp file after
    wg-quick has read it — see connect().
    """
    base_path = (
        leak_protection.generate_protected_config(name)
        if leak_protection.is_supported() and leak_protection_enabled(name)
        else config_path(name)
    )

    text = base_path.read_text()
    if not key_encryption.is_encrypted(text):
        return base_path, None

    if decrypted_private_key is None:
        raise PassphraseRequired(name)

    decrypted_text = re.sub(
        r"^(\s*PrivateKey\s*=\s*).+$",
        lambda m: m.group(1) + decrypted_private_key,
        text,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_DIR.chmod(0o700)
    temp_path = RUNTIME_DIR / base_path.name
    _write_private(temp_path, decrypted_text)
    return temp_path, temp_path


try:
    from pyzbar.pyzbar import decode as qr_decode
    from PIL import Image
    HAVE_QR = True
except ImportError:
    HAVE_QR = False


def connect(name, decrypted_private_key=None):
    """
    decrypted_private_key: only needed if the tunnel's PrivateKey is
    passphrase-encrypted (see key_encryption.py). If it is and this is
    None, raises PassphraseRequired instead of attempting to connect —
    the caller (on the main thread, since getting the passphrase means
    showing a Qt prompt) should catch that, ask the user, decrypt with
    key_encryption.decrypt_key(), and call connect() again with the
    result. Not supported on Windows yet — WireGuard for Windows reads
    its config directly via wireguard.exe, bypassing wg-quick entirely,
    so it has no path through _effective_config_path's decryption step.
    """
    if IS_WINDOWS:
        wireguard = find_wireguard_exe()
        if not wireguard:
            return False, "wireguard.exe not found. Install WireGuard for Windows first."
        conf = str(config_path(name))
        argv = [wireguard, "/installtunnelservice", conf]
        temp_path = None
    else:
        wg_quick = find_wg_quick()
        if not wg_quick:
            return False, "wg-quick not found. Install wireguard-tools first."
        try:
            conf_path, temp_path = _effective_config_path(name, decrypted_private_key)
        except PassphraseRequired:
            raise
        except Exception as e:
            # _effective_config_path can raise (e.g. leak_protection's
            # already-derived-name guard, or a file I/O error regenerating
            # the protected config) — never let that escape connect()
            # uncaught. An uncaught exception here previously meant the
            # toggle button would silently stop responding until the kill
            # switch checkbox was manually re-toggled (which happened to
            # reset the leak_protection state that was tripping the guard).
            return False, f"Couldn't prepare config for '{name}': {e}"
        conf = str(conf_path)
        if IS_MAC:
            bash = find_bash()
            argv = [bash, wg_quick, "up", conf]
        else:
            argv = [wg_quick, "up", conf]

    try:
        ok, out = run_privileged(argv)
    finally:
        # The decrypted temp config only ever needs to exist for the
        # instant wg-quick reads it at startup — delete it right after,
        # success or failure, so the plaintext key doesn't sit on disk
        # any longer than necessary.
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

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
        # (If the tunnel's PrivateKey is encrypted, config_path(name)
        # still has the encrypted marker in it here rather than a
        # decrypted key — that's fine, wg-quick's "down" path never
        # actually reads PrivateKey's value, only PreDown/PostDown and
        # the interface name derived from the filename.)
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
    _write_private(dest, Path(src_path).read_text())


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
    _write_private(dest, payload)
