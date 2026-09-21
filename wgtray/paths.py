"""On-disk locations. Split out on its own so every other module can
import it without pulling in Qt or subprocess."""
from pathlib import Path

APP_DIR = Path.home() / ".config" / "wg-tray"
CONFIGS_DIR = APP_DIR / "configs"
STATE_FILE = APP_DIR / "state.json"

# Ephemeral, decrypted-at-connect-time configs live here, never CONFIGS_DIR
# — see key_encryption.py / wireguard.py's connect(). Plaintext private
# keys from a passphrase-protected tunnel only ever touch disk in this
# directory, and only for the moment wg-quick needs to read them.
RUNTIME_DIR = APP_DIR / "runtime"
