#!/usr/bin/env python3
"""
wg-tray — a tiny, open-source, no-telemetry WireGuard tray client.

Lives in your system tray like Mullvad/OpenVPN's app, but is just a thin
GUI wrapper around the real WireGuard tooling you already trust. No
accounts, no phone-home, no bundled analytics — it shells out to
wg-quick (Linux/macOS) or wireguard.exe (Windows) and nothing else.

Works on:
  - Linux (tested target: Artix + KDE, but any DE with a tray works)
  - macOS (uses the wireguard-tools you installed via Homebrew)
  - Windows (uses the official WireGuard for Windows install)

Import a config either as a .conf file, or by pointing it at a PNG/JPG
screenshot of a QR code (e.g. one shown by your wg-panel) — it'll decode
the WireGuard config straight out of the image, no phone needed.

This file is intentionally just an entry point; the implementation lives
in the wgtray/ package (see wgtray/app.py for where startup begins).
"""
from wgtray.app import main

if __name__ == "__main__":
    main()
