"""Optional, per-tunnel passphrase encryption for a config's PrivateKey.

Off by default. When a passphrase is set for a tunnel, its PrivateKey
line in the on-disk .conf is replaced with an encrypted blob instead of
the raw key — so a stolen/copied config file (or a laptop with an
unencrypted disk) doesn't hand over the key outright. Everything else in
the file (Address, the [Peer] section, etc.) stays plaintext; none of it
is sensitive the way the private key is.

wg-quick itself has no concept of an encrypted key — it just needs a
plain .conf with a real PrivateKey line. So connecting a passphrase-
protected tunnel means: prompt for the passphrase, decrypt the key in
memory, write a temporary plaintext .conf to a private, 0600 location,
point wg-quick at that, and delete it again immediately after wg-quick
has read it (it only needs the file at startup, not while the tunnel is
running).

Encryption: AES-256-GCM (authenticated — a wrong passphrase or a
tampered blob fails to decrypt rather than silently returning garbage)
with a key derived from the passphrase via scrypt (memory-hard, so
brute-forcing a stolen blob is expensive even for a short passphrase).
"""
import base64
import json
import os
import re

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MARKER_PREFIX = "wgtray-encrypted-v1:"
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32


class DecryptionError(Exception):
    pass


def _derive_key(passphrase, salt):
    kdf = Scrypt(salt=salt, length=KEY_SIZE, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_key(private_key, passphrase):
    """Returns the marker string to store in place of a plaintext
    PrivateKey value: "wgtray-encrypted-v1:<base64 JSON blob>"."""
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    derived = _derive_key(passphrase, salt)
    ciphertext = AESGCM(derived).encrypt(nonce, private_key.encode("utf-8"), None)
    payload = {
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return MARKER_PREFIX + base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def decrypt_key(marker, passphrase):
    """Raises DecryptionError on a wrong passphrase or corrupted/tampered
    blob — AES-GCM is authenticated, so this fails cleanly rather than
    returning garbage that looks like a key."""
    if not marker.startswith(MARKER_PREFIX):
        raise DecryptionError("Not an encrypted key marker.")
    try:
        payload = json.loads(base64.b64decode(marker[len(MARKER_PREFIX):]))
        salt = base64.b64decode(payload["salt"])
        nonce = base64.b64decode(payload["nonce"])
        ciphertext = base64.b64decode(payload["ciphertext"])
        derived = _derive_key(passphrase, salt)
        plaintext = AESGCM(derived).decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except InvalidTag:
        raise DecryptionError("Wrong passphrase.")
    except (KeyError, ValueError, TypeError) as e:
        raise DecryptionError(f"Corrupted encrypted key: {e}")


def is_encrypted(config_text):
    key_line = _find_private_key_line(config_text)
    return key_line is not None and key_line.startswith(MARKER_PREFIX)


def get_encrypted_marker(config_text):
    """Returns the raw "wgtray-encrypted-v1:..." marker string from a
    config's PrivateKey line, or None if it isn't encrypted (or has no
    PrivateKey at all) — for callers (e.g. the passphrase prompt) that
    need to pass the marker itself to decrypt_key()."""
    key_line = _find_private_key_line(config_text)
    if key_line is not None and key_line.startswith(MARKER_PREFIX):
        return key_line
    return None


def _find_private_key_line(config_text):
    m = re.search(r"^\s*PrivateKey\s*=\s*(.+)$", config_text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def encrypt_config(config_text, passphrase):
    """Returns config_text with its PrivateKey value replaced by an
    encrypted marker. Raises ValueError if there's no PrivateKey line."""
    key = _find_private_key_line(config_text)
    if key is None:
        raise ValueError("Config has no PrivateKey line to encrypt.")
    if key.startswith(MARKER_PREFIX):
        raise ValueError("Config's PrivateKey is already encrypted.")
    marker = encrypt_key(key, passphrase)
    return re.sub(
        r"^(\s*PrivateKey\s*=\s*).+$",
        lambda m: m.group(1) + marker,
        config_text,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )


def decrypt_config(config_text, passphrase):
    """Returns config_text with its encrypted PrivateKey marker replaced
    by the real plaintext key. Raises DecryptionError on a wrong
    passphrase; ValueError if the config isn't actually encrypted."""
    marker = _find_private_key_line(config_text)
    if marker is None or not marker.startswith(MARKER_PREFIX):
        raise ValueError("Config's PrivateKey isn't encrypted.")
    key = decrypt_key(marker, passphrase)
    return re.sub(
        r"^(\s*PrivateKey\s*=\s*).+$",
        lambda m: m.group(1) + key,
        config_text,
        count=1,
        flags=re.MULTILINE | re.IGNORECASE,
    )
