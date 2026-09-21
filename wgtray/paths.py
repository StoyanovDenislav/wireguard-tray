"""On-disk locations. Split out on its own so every other module can
import it without pulling in Qt or subprocess."""
from pathlib import Path

APP_DIR = Path.home() / ".config" / "wg-tray"
CONFIGS_DIR = APP_DIR / "configs"
STATE_FILE = APP_DIR / "state.json"
