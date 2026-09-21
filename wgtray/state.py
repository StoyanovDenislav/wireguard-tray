"""Persisted app state: which tunnel is active, imported configs, and
the user's update-check preferences."""
import json

from .paths import APP_DIR, CONFIGS_DIR, STATE_FILE

DEFAULT_STATE = {
    "active": None,
    "seen_version": None,
    "auto_update_check": False,
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
    return sorted(p.stem for p in CONFIGS_DIR.glob("*.conf"))


def config_path(name):
    return CONFIGS_DIR / f"{name}.conf"
