"""Opt-in kill switch + DNS/IPv6 leak guard for macOS and Linux.

Implemented as PostUp/PreDown hooks in a *derived* copy of the user's
.conf (never mutating the original), calling a bundled per-OS shell
script (wgtray/resources/leak_protection_{macos,linux}.sh — macOS uses
pf, Linux uses nftables). wg-quick already runs PostUp/PreDown as root —
same trust boundary as `wg-quick up` itself, nothing new is granted here.

DNS handling on both platforms is a firewall block rule (port 53 on the
physical interfaces), not a pin to the tunnel's resolver — pinning is
fragile if the tunnel drops mid-resolution (you'd get a timeout against
an unreachable resolver instead of a clean, immediate block), and on
Linux it would also mean detecting and handling systemd-resolved vs
NetworkManager vs a plain resolv.conf across every init system
(Artix's runit/OpenRC/s6/dinit variants included) — the firewall rule
sidesteps all of that entirely. The kill switch already blocks
everything else on the physical interfaces; the DNS rule is mostly
belt-and-suspenders for the brief window while the tunnel is up.

Windows kill switches need WFP, a much bigger lift, and aren't
attempted here.
"""
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from .paths import CONFIGS_DIR
from .platform_utils import IS_LINUX, IS_MAC

DEFAULT_ENDPOINT_PORT = "51820"

_SCRIPT_NAMES = {
    "macos": "leak_protection_macos.sh",
    "linux": "leak_protection_linux.sh",
}


def _current_platform_key():
    if IS_MAC:
        return "macos"
    if IS_LINUX:
        return "linux"
    return None


def _script_name():
    key = _current_platform_key()
    return _SCRIPT_NAMES[key] if key else None


# wg-quick derives the network interface name from the config file's
# basename and requires it to be <=15 characters (a Linux/BSD interface
# name limit it enforces even on macOS) — see wg-quick's own regex:
# [a-zA-Z0-9_=+.-]{1,15}\.conf$. A naive "<name>.protected.conf" blows
# past that for almost any real tunnel name (e.g. "client1.protected" is
# already 17 chars), so derived configs instead get a short, deterministic
# name built from a hash of the original tunnel name: always well under
# the limit regardless of how long or short the user's own name is.
DERIVED_PREFIX = "wgtp"  # "wg tray protected"
_MANIFEST_FILE_NAME = ".leak_protection_manifest.json"


def _derived_stem(name):
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
    return f"{DERIVED_PREFIX}{digest}"


def _bundled_script_path():
    # Next to this file when run from source; PyInstaller's onedir/onefile
    # layout keeps package data alongside the package, so this also holds
    # for the packaged app as long as the .spec collects wgtray/resources.
    return Path(__file__).parent / "resources" / _script_name()


def _installed_script_path():
    return CONFIGS_DIR.parent / _script_name()


def _ensure_script_installed():
    """Copy the bundled hook script to the app's config dir (outside of
    Program Files/.app on all platforms) so wg-quick's PostUp/PreDown —
    which run as root via pkexec/osascript — can find and execute it at a
    stable, predictable path regardless of where wg-tray itself is installed."""
    src = _bundled_script_path()
    dest = _installed_script_path()
    if not dest.exists() or dest.read_bytes() != src.read_bytes():
        dest.write_bytes(src.read_bytes())
        dest.chmod(0o755)
    return dest


def _extract(pattern, text, default=None):
    m = re.search(pattern, text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else default


def _manifest_path():
    return CONFIGS_DIR / _MANIFEST_FILE_NAME


def _load_manifest():
    """{derived_stem: original_tunnel_name}, so is_protected_filename()
    can recognize a derived config purely from its short hashed name,
    without re-deriving every possible name's hash."""
    path = _manifest_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_manifest(manifest):
    _manifest_path().write_text(json.dumps(manifest))


def is_protected_filename(filename):
    """True for a derived config's filename (a short wgtp<hash>.conf),
    so callers can filter these out of the user-facing tunnel list —
    they're generated artifacts living in the same directory as real
    configs, not tunnels a user imported."""
    stem = filename[:-len(".conf")] if filename.endswith(".conf") else filename
    return stem in _load_manifest()


def protected_config_path(name):
    return CONFIGS_DIR / f"{_derived_stem(name)}.conf"


def generate_protected_config(name):
    """
    Read configs/<name>.conf, and write a short-named derived config
    (configs/wgtp<hash>.conf — see the module docstring for why it can't
    just be "<name>.protected.conf"): the same [Interface]/[Peer] content
    plus PostUp/PreDown lines that invoke the leak-protection script.
    Returns the derived path.
    """
    if not is_supported():
        raise RuntimeError("Leak protection isn't supported on this platform/setup.")

    if name in _load_manifest():
        # Guards against ever protecting an already-derived config's own
        # name (i.e. name is itself a derived stem like "wgtp1234567890",
        # a manifest *key* — not to be confused with .values(), which are
        # the original tunnel names every successfully-protected tunnel
        # legitimately appears as after its first connect; checking
        # .values() here was a bug that broke every reconnect after the
        # first one). Unreachable in normal use since list_configs()
        # filters derived files out of the tunnel list entirely, but fail
        # loudly rather than silently generating nonsense if something
        # upstream regresses.
        raise ValueError(f"'{name}' looks like an already-derived leak-protection config.")

    original = CONFIGS_DIR / f"{name}.conf"
    text = original.read_text()

    endpoint = _extract(r"^\s*Endpoint\s*=\s*(.+)$", text, default="")
    port = endpoint.rsplit(":", 1)[-1].strip() if ":" in endpoint else DEFAULT_ENDPOINT_PORT
    if not port.isdigit():
        port = DEFAULT_ENDPOINT_PORT

    script = _ensure_script_installed()

    # Strip any pre-existing PostUp/PreDown so re-generating is idempotent
    # and doesn't stack duplicate hooks if the user toggles protection on
    # and off a few times.
    lines = [
        line for line in text.splitlines()
        if not re.match(r"^\s*(PostUp|PreDown|PostDown|PreUp)\s*=", line, re.IGNORECASE)
    ]

    # Insert hooks right after the [Interface] section header's block —
    # wg-quick doesn't care about ordering within the section, so
    # appending at the end of the file's [Interface] lines is simplest:
    # just add them right after the first line matching "[Interface]".
    out = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.strip().lower() == "[interface]":
            out.append(f'PostUp = {script} up {port}')
            out.append(f'PreDown = {script} down {port}')
            inserted = True

    protected = protected_config_path(name)
    # 0600 from creation, not write-then-chmod — this file can contain a
    # plaintext PrivateKey (leak protection copies whatever's in the
    # original, encrypted or not — see wireguard._effective_config_path
    # for where an encrypted one gets its key substituted back in before
    # this function is even called for that combination), and write-then-
    # chmod leaves a brief window at default, umask-dependent permissions.
    fd = os.open(protected, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")

    manifest = _load_manifest()
    manifest[protected.stem] = name
    _save_manifest(manifest)

    return protected


def remove_protected_config(name):
    protected = protected_config_path(name)
    protected.unlink(missing_ok=True)

    manifest = _load_manifest()
    manifest.pop(protected.stem, None)
    _save_manifest(manifest)


def is_supported():
    if IS_MAC:
        return shutil.which("pfctl") is not None
    if IS_LINUX:
        return shutil.which("nft") is not None
    return False
