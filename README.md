# wg-tray
(Yes, this is vibecoded as heck, I just wanted a simple tool, no time to write code, sorry.)

A tiny, open-source, no-telemetry WireGuard tray client. Lives in your system
tray like Mullvad/OpenVPN's app, but is just a thin GUI wrapper around the
real WireGuard tooling you already trust — no accounts, no phone-home, no
bundled analytics.

Built partly out of spite for the official WireGuard macOS app being locked
behind the App Store with its own signing hoops — this is just the simple,
open-source client it should've been in the first place.

Works on Linux, macOS, and Windows.

## Scope

This is a basic, personal-use tool — think "connect to my home server/NAS
or a personal VPS," not "secure a fleet of enterprise endpoints." It hasn't
had a formal security audit, there's no central management, no policy
enforcement, no MDM integration, and no support contract. If you need
enterprise-grade WireGuard tooling, this isn't it — look at something like
Tailscale, Headscale, or a commercial WireGuard management platform instead.

## Install

### Option 1: Download a prebuilt release (easiest)

Grab the latest build for your OS from the [Releases page](../../releases):

- **macOS**
  - `wg-tray-macos.dmg` (recommended) — open, drag `wg-tray.app` to Applications.
  - `wg-tray-macos.zip` — unzip → drag `wg-tray.app` to Applications.
  - Either way, first launch: right-click → Open (it's unsigned, so Gatekeeper
    will warn once).
- **Linux**
  - `wg-tray-x86_64.AppImage` (recommended) — `chmod +x` it, then run it
    directly. No install, no distro-specific package, works across most
    modern distros.
  - `wg-tray-linux.tar.gz` — extract → run `./wg-tray/wg-tray`, if you'd
    rather have a plain folder.
- **Windows**
  - `wg-tray-windows-setup.exe` (recommended) — a normal installer, adds
    Start Menu/desktop shortcuts.
  - `wg-tray-windows.zip` — extract → run `wg-tray.exe`, no install.

Every push to `main` also builds fresh binaries for all three platforms,
downloadable from the [Actions tab](../../actions) if you want a build newer
than the latest tagged release.

## Code layout

`wg_tray.py` is just the entry point; the implementation lives in the
`wgtray/` package:

- `platform_utils.py` — OS detection + privilege-escalated command exec
  (pkexec/osascript/UAC).
- `paths.py` / `state.py` — on-disk config dir + persisted state (active
  tunnel, update-check preferences).
- `wireguard.py` — connect/disconnect and config import (.conf, QR image).
- `leak_protection.py` + `resources/leak_protection_macos.sh` — the
  opt-in macOS kill switch/DNS/IPv6 guard (see below).
- `updater.py` — GitHub releases API check (see "Update checking" below).
- `theme.py` — the dark QSS stylesheet and the code-drawn tunnel icon.
- `ui/main_window.py`, `ui/dialogs.py` — the sidebar window, Settings, and
  changelog dialogs.
- `tray.py` — the tray icon/menu, wiring the above together.
- `app.py` — startup: OS app-identity setup, QApplication, launches `tray.py`.

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

## Kill switch + leak protection (macOS only, opt-in)

Per-tunnel checkbox: "Kill switch + leak protection (macOS)". Off by
default — enabling it doesn't touch other tunnels, and existing configs
keep working exactly as before if you leave it off. Checking it shows a
confirmation dialog first, since a kill switch means **losing internet
entirely** if the tunnel drops, not just losing the VPN — that's the
whole point, but it's worth confirming rather than a silent surprise.

When enabled for a tunnel, connecting no longer runs wg-quick against your
imported `.conf` directly. Instead wg-tray generates a derived copy (never
modifying the original) with `PostUp`/`PreDown` hooks added, and those hooks
run a bundled script (`wgtray/resources/leak_protection_macos.sh`) that:

1. **Kill switch** — loads a `pf` anchor covering every physical network
   interface (Wi-Fi, built-in Ethernet, Thunderbolt bridges, USB dongles —
   enumerated dynamically, not hardcoded to `en0`), blocking everything
   except DHCP and the WireGuard endpoint's own port, and passing
   everything on the tunnel's `utun*` interface. If the tunnel drops
   unexpectedly, your physical interfaces stay blocked instead of
   silently leaking your real IP.
2. **DNS blocking** — the same pf anchor blocks outbound DNS (port 53) on
   every physical interface. This blocks rather than pins to the tunnel's
   resolver — pinning is fragile if the tunnel drops mid-resolution (a
   timeout against an unreachable resolver instead of a clean block).
3. **IPv6 guard** — disables IPv6 on every physical interface while
   connected, since most WireGuard configs only route `0.0.0.0/0` and
   IPv6 traffic would otherwise bypass the tunnel entirely.

Disconnecting (or unchecking the box before reconnecting) restores your
original IPv6 settings and unloads the pf anchor. The checkbox is disabled
while that tunnel is connected, since flipping it mid-connection would
tear it down via a different config than it came up with.

**If wg-tray or the tunnel is force-quit while connected** (so `PreDown`
never runs), the next time you connect *any* protected tunnel, wg-tray
detects the leftover state and restores IPv6 automatically before
proceeding. If you don't reconnect anything and just want your original
IPv6 setting back immediately, run:
```
sudo networksetup -setv6automatic "Wi-Fi"    # or your interface's service name
```
(`networksetup -listallnetworkservices` lists the exact names.) The pf
anchor itself doesn't need manual cleanup — `pfctl -a wg-tray-leakguard -F all`
flushes it, though a reboot or `pfctl -d`/`-e` cycle also clears it.

This needs `pfctl`, which is standard on macOS — nothing extra to install.
Not yet available on Linux (an iptables/nftables equivalent is a natural
follow-up) or Windows (needs the Windows Filtering Platform, a bigger
lift, and isn't implemented).

## Update checking

wg-tray never phones home on its own. There's no background process, no
bundled analytics SDK, and no update check runs unless you trigger it:

- **Settings → Check for updates now**: a single, one-off, unauthenticated
  GET to GitHub's public releases API (`api.github.com`) — the same request
  your browser makes if you open the Releases page yourself. No account,
  hardware ID, or usage data is attached.
- **Settings → Automatically check for updates**: an opt-in toggle,
  **off by default**. When enabled, it repeats that same request every few
  hours and shows a tray notification if a newer version exists. Turning it
  on doesn't change what's sent — same anonymous request, just on a timer.
  It never auto-downloads or auto-installs anything; you still choose when
  and whether to grab the new build.

After you install an update, wg-tray shows a one-time "What's new" screen
pulled from that version's GitHub Release notes.

## Releasing a new version

Push a tag like `v0.2.0` — GitHub Actions builds all three platforms and
attaches them to a new GitHub Release automatically. The release notes
GitHub generates for that tag double as the in-app changelog shown to
users after they update, so a clear commit history matters here.

```bash
git tag v0.2.0
git push origin v0.2.0
```

Also bump `APP_VERSION` in [wgtray/\_\_init\_\_.py](wgtray/__init__.py) to match the tag —
it's what the app compares against GitHub's latest release to decide if
an update is available, and what gates the one-time changelog popup.
