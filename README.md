# wg-tray

A tiny, open-source, no-telemetry WireGuard tray client. Lives in your system
tray like Mullvad/OpenVPN's app, but is just a thin GUI wrapper around the
real WireGuard tooling you already trust — no accounts, no phone-home, no
bundled analytics.

Works on Linux, macOS, and Windows.

## Install

### Option 1: Download a prebuilt release (easiest)

Grab the latest build for your OS from the [Releases page](../../releases):

- **macOS** — `wg-tray-macos.zip` → unzip → drag `wg-tray.app` to Applications.
  First launch: right-click → Open (it's unsigned, so Gatekeeper will warn once).
- **Linux** — `wg-tray-linux.tar.gz` → extract → run `./wg-tray/wg-tray`.
- **Windows** — `wg-tray-windows.zip` → extract → run `wg-tray.exe`.

Every push to `main` also builds fresh binaries for all three platforms,
downloadable from the [Actions tab](../../actions) if you want a build newer
than the latest tagged release.

### Option 2: Run from source

Requires Python 3.9+.

```bash
git clone <this repo>
cd wg_tray
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python wg_tray.py
```

### Option 3: Build your own binary

```bash
# macOS / Linux
./build.sh

# Windows (PowerShell)
.\build.ps1
```

Output lands in `dist/`.

## Runtime requirements

- **Linux / macOS**: `wireguard-tools` (provides `wg-quick`) must be installed
  and on your PATH. macOS: `brew install wireguard-tools`. Linux: your distro's
  package (e.g. `pacman -S wireguard-tools`, `apt install wireguard-tools`).
- **Windows**: the official [WireGuard for Windows](https://www.wireguard.com/install/)
  client must be installed (it ships `wireguard.exe`, which this app drives).
- QR-code import needs `zbar`: `brew install zbar` (macOS) or
  `apt install libzbar0` / `pacman -S zbar` (Linux). Windows: bundled via the
  `pyzbar`/`pillow` pip packages, no extra system install needed.

## Privilege escalation

Bringing a tunnel up/down needs admin rights. This app never asks for or
stores a password itself — it always hands off to your OS's native prompt:

- Linux: `pkexec` (polkit's graphical sudo prompt)
- macOS: `osascript` administrator-privileges dialog
- Windows: native UAC prompt

## Releasing a new version

Push a tag like `v0.2.0` — GitHub Actions builds all three platforms and
attaches them to a new GitHub Release automatically.

```bash
git tag v0.2.0
git push origin v0.2.0
```
