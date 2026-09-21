"""Parsing/validation helpers for editing a tunnel's raw .conf, shared by
the config editor dialog's raw-text and structured-form modes.

Editing always happens on the original, as-imported config (never a
leak_protection-derived .protected copy) — see wireguard.config_path.
"""
import re

# Fields the structured-form editor exposes directly. Anything else
# present in a real .conf (MTU, Table, PreUp/PostUp/PreDown/PostDown,
# SaveConfig, comments, ...) is preserved verbatim by keeping the
# original lines and only replacing the ones for fields being edited —
# never round-tripped through a parsed-and-rebuilt structure that could
# silently drop something the user (or another tool) put there.
INTERFACE_FIELDS = ["PrivateKey", "Address", "DNS", "ListenPort", "MTU"]
PEER_FIELDS = ["PublicKey", "PresharedKey", "Endpoint", "AllowedIPs", "PersistentKeepalive"]


class ConfigValidationError(ValueError):
    pass


def parse_sections(text):
    """
    Very small, line-oriented .conf parser: returns a list of
    (section_name, [(key, value, original_line_index), ...]) tuples,
    plus the raw lines list, good enough for the structured-form editor
    to read known fields from and write them back without disturbing
    anything else in the file.
    """
    lines = text.splitlines()
    sections = []
    current = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        section_match = re.match(r"^\[(\w+)\]$", stripped)
        if section_match:
            current = (section_match.group(1), [])
            sections.append(current)
            continue
        if current is None or not stripped or stripped.startswith("#"):
            continue
        kv_match = re.match(r"^(\w+)\s*=\s*(.*)$", stripped)
        if kv_match:
            current[1].append((kv_match.group(1), kv_match.group(2).strip(), i))
    return sections, lines


def get_field(text, section_name, key, default=""):
    sections, _ = parse_sections(text)
    for name, fields in sections:
        if name.lower() != section_name.lower():
            continue
        for k, v, _ in fields:
            if k.lower() == key.lower():
                return v
    return default


def set_field(text, section_name, key, value):
    """
    Returns new config text with `key = value` set inside the first
    [section_name] block, replacing the existing line if present,
    otherwise appending it to that section. If value is empty and the
    field isn't required, the existing line (if any) is removed instead
    of writing "Key = ".
    """
    sections, lines = parse_sections(text)
    for name, fields in sections:
        if name.lower() != section_name.lower():
            continue
        for k, v, line_idx in fields:
            if k.lower() == key.lower():
                if value:
                    lines[line_idx] = f"{key} = {value}"
                else:
                    lines[line_idx] = None  # marked for removal
                return "\n".join(l for l in lines if l is not None)
        # Field not present yet in this section — append right after the
        # section header line.
        if value:
            header_idx = next(
                i for i, line in enumerate(lines)
                if re.match(rf"^\[{re.escape(section_name)}\]$", line.strip(), re.IGNORECASE)
            )
            lines.insert(header_idx + 1, f"{key} = {value}")
        return "\n".join(lines)
    # Section doesn't exist at all yet — only realistic for a from-scratch
    # config, which the editor doesn't create, but handle it rather than
    # silently drop the value.
    if value:
        lines += ["", f"[{section_name}]", f"{key} = {value}"]
    return "\n".join(lines)


def validate(text):
    """
    Raises ConfigValidationError with a human-readable message if the
    config is missing anything wg-quick requires to bring the tunnel up
    at all. Deliberately not exhaustive (doesn't validate key format,
    AllowedIPs CIDR syntax, etc.) — just enough to catch "this will
    obviously fail to connect" before saving over a working config.
    """
    sections, _ = parse_sections(text)
    section_names = [name.lower() for name, _ in sections]

    if "interface" not in section_names:
        raise ConfigValidationError("Missing [Interface] section.")
    if "peer" not in section_names:
        raise ConfigValidationError("Missing [Peer] section.")

    if not get_field(text, "Interface", "PrivateKey"):
        raise ConfigValidationError("[Interface] is missing PrivateKey.")
    if not get_field(text, "Interface", "Address"):
        raise ConfigValidationError("[Interface] is missing Address.")
    if not get_field(text, "Peer", "PublicKey"):
        raise ConfigValidationError("[Peer] is missing PublicKey.")
    if not get_field(text, "Peer", "AllowedIPs"):
        raise ConfigValidationError("[Peer] is missing AllowedIPs.")
