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
    auto-fills this from commits via generate_release_notes), and
    'url', or None on any failure. Failures (offline, rate-limited,
    etc.) are silent — this is a nice-to-have, never something that
    should interrupt the user.
    """
    try:
        req = urllib.request.Request(RELEASES_API_URL, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context()) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {
            "version": data.get("tag_name", "").lstrip("v"),
            "notes": data.get("body", "").strip(),
            "url": data.get("html_url", RELEASES_PAGE_URL),
        }
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, json.JSONDecodeError, KeyError):
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
