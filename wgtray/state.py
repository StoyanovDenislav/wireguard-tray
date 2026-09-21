"""Persisted app state: which tunnel is active, imported configs, and
the user's update-check preferences."""
import json

from .leak_protection import is_protected_filename
from .paths import APP_DIR, CONFIGS_DIR, STATE_FILE

DEFAULT_STATE = {
    "active": None,
    "seen_version": None,
    "auto_update_check": False,
    "leak_protection": {},  # {tunnel_name: bool}, macOS/Linux only
}


def ensure_dirs():
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps(DEFAULT_STATE))


def load_state():
    ensure_dirs()
    try:
        state = json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        state = {}
    # Backfill any keys older state files on disk don't have yet.
    for key, default in DEFAULT_STATE.items():
        state.setdefault(key, default)
    return state


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def list_configs():
    ensure_dirs()
    # Exclude leak_protection.py's generated derived copies (e.g.
    # client1.protected.conf) — they live in the same directory as real
    # configs, but aren't tunnels a user imported, and would otherwise
    # show up as their own selectable "tunnels" in the sidebar.
    return sorted(
        p.stem for p in CONFIGS_DIR.glob("*.conf")
        if not is_protected_filename(p.name)
    )


def config_path(name):
    return CONFIGS_DIR / f"{name}.conf"


def leak_protection_enabled(name):
    return bool(load_state().get("leak_protection", {}).get(name, False))


def set_leak_protection(name, enabled):
    state = load_state()
    state.setdefault("leak_protection", {})[name] = bool(enabled)
    save_state(state)
