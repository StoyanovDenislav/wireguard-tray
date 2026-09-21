"""Update checking against GitHub's public releases API.

Privacy note: nothing in this module runs unless the user clicks
"Check for updates" or has explicitly opted in to automatic checks
(off by default). It's a single unauthenticated GET — same as opening
the Releases page in a browser. No hardware IDs, no analytics, no
custom telemetry server.
"""
import json
import ssl
import urllib.error
import urllib.request

GITHUB_REPO = "StoyanovDenislav/wireguard-tray"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"

_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "wg-tray"}


def _ssl_context():
    """
    A PyInstaller-frozen app doesn't ship the OS's CA trust store the way
    a normal Python install does, so the interpreter's default SSL
    context can fail to verify api.github.com's certificate — this is
    what "Couldn't reach GitHub" actually meant in packaged builds,
    masked by the broad except below. certifi bundles a CA file we can
    point the context at explicitly, which works the same whether
    running from source or frozen.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _parse_version(v):
    v = v.lstrip("v")
    parts = []
    for p in v.split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer_version(candidate, current):
    return _parse_version(candidate) > _parse_version(current)


def fetch_latest_release():
    """
    Returns a dict with 'version', 'notes' (the release body — CI
    auto-fills this from commits via generate_release_notes), 'url', and
    'assets' (list of {'name', 'download_url', 'size'} for every file
    attached to the release, used to find the right platform's binary
    for in-app updating), or None on any failure. Failures (offline,
    rate-limited, etc.) are silent — this is a nice-to-have, never
    something that should interrupt the user.
    """
    try:
        req = urllib.request.Request(RELEASES_API_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "version": data.get("tag_name", "").lstrip("v"),
            "notes": data.get("body", "").strip(),
            "url": data.get("html_url", RELEASES_PAGE_URL),
            "assets": [
                {
                    "name": a.get("name", ""),
                    "download_url": a.get("browser_download_url", ""),
                    "size": a.get("size", 0),
                }
                for a in data.get("assets", [])
            ],
        }
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None


def asset_for_platform(assets):
    """
    Pick the right release asset for the OS running right now, preferring
    the format self_update.py knows how to install unattended:
    Windows -> the Inno Setup installer .exe (silent-installable);
    macOS -> the .dmg (self_update.py mounts it and swaps the .app);
    Linux -> the AppImage (a single file we can replace in place).
    Returns None if nothing matches (e.g. running from source, or a
    release that's missing an asset for this platform).
    """
    from .platform_utils import IS_LINUX, IS_MAC, IS_WINDOWS

    if IS_WINDOWS:
        wanted = "windows-setup.exe"
    elif IS_MAC:
        wanted = "macos.dmg"
    elif IS_LINUX:
        wanted = "x86_64.appimage"
    else:
        return None

    for asset in assets:
        if asset["name"].lower().endswith(wanted):
            return asset
    return None


def fetch_release_notes_for(version):
    """Look up the changelog body for a specific tag (e.g. after an
    update), falling back to None if it can't be fetched."""
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/v{version}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("body", "").strip()
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, json.JSONDecodeError, KeyError):
        return None
