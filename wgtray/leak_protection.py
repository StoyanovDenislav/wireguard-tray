"""Opt-in kill switch + DNS/IPv6 leak guard for macOS.

Implemented as PostUp/PreDown hooks in a *derived* copy of the user's
.conf (never mutating the original), calling a bundled pf-based shell
script (see wgtray/resources/leak_protection_macos.sh). wg-quick already
runs PostUp/PreDown as root — same trust boundary as `wg-quick up` itself,
nothing new is granted here.

Linux support (iptables/nftables + resolvectl) is a natural follow-up but
out of scope for now. Windows kill switches need WFP, a much bigger lift,
and aren't attempted here.
"""
import re
import shutil
from pathlib import Path

from .paths import CONFIGS_DIR
from .platform_utils import IS_MAC

SCRIPT_NAME = "leak_protection_macos.sh"
DEFAULT_ENDPOINT_PORT = "51820"


def _bundled_script_path():
    # Next to this file when run from source; PyInstaller's onedir/onefile
    # layout keeps package data alongside the package, so this also holds
    # for the packaged app as long as the .spec collects wgtray/resources.
    return Path(__file__).parent / "resources" / SCRIPT_NAME


def _installed_script_path():
    return CONFIGS_DIR.parent / SCRIPT_NAME


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


def protected_config_path(name):
    return CONFIGS_DIR / f"{name}.protected.conf"


def generate_protected_config(name):
    """
    Read configs/<name>.conf, and write configs/<name>.protected.conf:
    the same [Interface]/[Peer] content plus PostUp/PreDown lines that
    invoke the leak-protection script. Returns the derived path.
    """
    if not IS_MAC:
        raise RuntimeError("Leak protection is currently macOS-only.")

    original = CONFIGS_DIR / f"{name}.conf"
    text = original.read_text()

    dns = _extract(r"^\s*DNS\s*=\s*(.+)$", text, default="1.1.1.1")
    # DNS can be a comma-separated list; the hook script wants one primary.
    dns = dns.split(",")[0].strip()

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
            out.append(f'PostUp = {script} up {dns} {port}')
            out.append(f'PreDown = {script} down {dns} {port}')
            inserted = True

    protected = protected_config_path(name)
    protected.write_text("\n".join(out) + "\n")
    protected.chmod(0o600)
    return protected


def remove_protected_config(name):
    protected_config_path(name).unlink(missing_ok=True)


def is_supported():
    return IS_MAC and shutil.which("pfctl") is not None
