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

- `platform_utils.py` — OS detection, privilege-escalated command exec
  (pkexec/osascript/UAC), and other-VPN conflict detection.
- `paths.py` / `state.py` — on-disk config dir + persisted state (active
  tunnel, update-check preferences).
- `wireguard.py` — connect/disconnect and config import (.conf, QR image).
- `leak_protection.py` + `resources/leak_protection_{macos,linux}.sh` —
  the opt-in kill switch/DNS/IPv6 guard (see below).
- `updater.py` — GitHub releases API check; `self_update.py` — downloads
  and installs an update in place per OS (see "Update checking and
  installing" below).
- `theme.py` — the dark QSS stylesheet and the code-drawn tunnel icon.
- `config_editor.py` + `ui/config_editor_dialog.py` — the raw-text/
  structured-form .conf editor (see "Editing a tunnel's config" below).
- `key_encryption.py` — optional per-tunnel passphrase encryption of the
  private key at rest (see "Encrypting a tunnel's private key" below).
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

## Editing a tunnel's config

Sometimes you need to tweak something wg-tray's UI doesn't expose —
add a second `AllowedIPs` range, set a custom `MTU`, add your own
`PostUp`/`PreDown` hook, etc. "Edit config…" in the tunnel detail pane
opens the config in either of two modes, switchable without losing
your edits:

- **Form**: labeled fields for the common ones (PrivateKey, Address,
  DNS, ListenPort, MTU, PublicKey, PresharedKey, Endpoint, AllowedIPs,
  PersistentKeepalive). Anything else in the file — comments, hooks,
  directives the form doesn't list — is left exactly as-is; the form
  only ever rewrites the specific lines for fields you actually change.
- **Raw text**: the file's exact contents, for anything the form
  doesn't cover.

Saving validates that the result still has everything wg-quick needs to
bring the tunnel up at all (both sections present, PrivateKey, Address,
PublicKey, AllowedIPs) before writing — it won't silently save something
that's obviously going to fail to connect. Disabled while that tunnel is
connected, since editing the file it's currently using can leave it in
a mismatched state until you reconnect.

## Encrypting a tunnel's private key at rest (macOS + Linux, opt-in)

By default, a tunnel's `.conf` — including its `PrivateKey` — sits on
disk as plain text (with `0600` permissions, but still plainly readable
by root or anyone with access to the file, e.g. a stolen laptop with an
unencrypted disk). "Set passphrase…" in the config editor's Encryption
row replaces the `PrivateKey` line with an AES-256-GCM-encrypted blob
(key derived from your passphrase via scrypt) instead of the raw key.
Off by default; only applies to tunnels you explicitly set a passphrase
for.

Once set, connecting that tunnel prompts for the passphrase every time
— it's never cached, not even for the app's current run. The decrypted
key only ever touches disk in a private runtime directory
(`~/.config/wg-tray/runtime/`, `0700`, files `0600`), just long enough
for `wg-quick` to read it at startup, and is deleted immediately after
(successful connect or not). Disconnecting doesn't need the passphrase
— wg-quick's teardown path never reads `PrivateKey`'s actual value.

"Change passphrase…" (same button, once one's set) asks for the current
passphrase first, then lets you set a new one or remove encryption
entirely (back to plain text). AES-GCM is authenticated, so a wrong
passphrase or a corrupted/tampered blob fails cleanly with an error
rather than silently producing garbage.

Not yet supported on Windows — `wireguard.exe` reads its config
directly rather than going through `wg-quick`, so there's no point in
the flow to intercept and decrypt it. Encrypted tunnels currently can't
be connected on Windows; disconnect and editing are unaffected.

## Other VPN conflict detection (Linux/macOS)

wg-tray manages a single WireGuard tunnel and doesn't coordinate with
other VPN clients. If another VPN (Tailscale, Mullvad, a corporate VPN,
another WireGuard tunnel, etc.) already holds your Mac/Linux box's
default route when you try to connect, `wg-quick`'s own route setup
breaks in confusing ways — it picks the *first* "default" line out of
the routing table as the gateway to route the WireGuard endpoint through,
and if that's another VPN's tunnel interface instead of your real
gateway, it fails with something like:
```
route: bad address: utun4
```

Before attempting to connect, wg-tray checks for this and, if detected,
shows a dialog naming the likely cause instead of letting that cryptic
failure surface. For a short list of VPN clients with a well-known,
official CLI disconnect command (currently Mullvad, Tailscale), it also
offers a "Disconnect X" button that runs exactly that command — nothing
guessed or improvised for VPNs it doesn't specifically recognize; those
just get named so you can quit them yourself. You can also choose
"Connect anyway" if you know what you're doing.

## Kill switch + leak protection (macOS + Linux, opt-in)

Per-tunnel checkbox: "Kill switch + leak protection". Off by default —
enabling it doesn't touch other tunnels, and existing configs keep
working exactly as before if you leave it off. Checking it shows a
confirmation dialog first, since a kill switch means **losing internet
entirely** if the tunnel drops, not just losing the VPN — that's the
whole point, but it's worth confirming rather than a silent surprise.

When enabled for a tunnel, connecting no longer runs wg-quick against your
imported `.conf` directly. Instead wg-tray generates a derived copy (never
modifying the original) with `PostUp`/`PreDown` hooks added, calling a
bundled script — `leak_protection_macos.sh` (pf) or
`leak_protection_linux.sh` (nftables), picked automatically for the OS —
that:

1. **Kill switch** — blocks every physical network interface (Wi-Fi,
   Ethernet, USB dongles, Thunderbolt bridges — enumerated dynamically,
   never hardcoded to one interface name) except DHCP and the WireGuard
   endpoint's own port, while passing everything on the tunnel's own
   interface. If the tunnel drops unexpectedly, your physical interfaces
   stay blocked instead of silently leaking your real IP.
2. **DNS blocking** — the same firewall rule blocks outbound DNS (port
   53) on every physical interface, rather than pinning DNS to the
   tunnel's resolver — pinning is fragile if the tunnel drops
   mid-resolution (a timeout against an unreachable resolver instead of
   a clean block). On Linux this also sidesteps needing to detect or
   configure systemd-resolved vs NetworkManager vs a plain resolv.conf —
   the firewall rule works the same regardless of init system or DNS
   manager (Artix's runit/OpenRC/s6/dinit variants included).
3. **IPv6 guard** — disables IPv6 on every physical interface while
   connected (via `networksetup` on macOS, `sysctl` on Linux), since
   most WireGuard configs only route `0.0.0.0/0` and IPv6 traffic would
   otherwise bypass the tunnel entirely.

Disconnecting (or unchecking the box before reconnecting) restores your
original IPv6 settings and removes the firewall rule. The checkbox is
disabled while that tunnel is connected, since flipping it mid-connection
would tear it down via a different config than it came up with.

**If wg-tray or the tunnel is force-quit while connected** (so `PreDown`
never runs), the next time you connect *any* protected tunnel, wg-tray
detects the leftover state and restores IPv6 automatically before
proceeding. If you don't reconnect anything and just want your original
IPv6 setting back immediately:
- **macOS**: `sudo networksetup -setv6automatic "Wi-Fi"` (or your
  interface's service name — `networksetup -listallnetworkservices`
  lists them). The pf anchor doesn't need manual cleanup —
  `pfctl -a wg-tray-leakguard -F all` flushes it, though a reboot or
  `pfctl -d`/`-e` cycle also clears it.
- **Linux**: `sudo sysctl net.ipv6.conf.<iface>.disable_ipv6=0` for each
  physical interface. The nftables table doesn't need manual cleanup —
  `sudo nft delete table inet wgtray_leakguard` removes it, though a
  reboot also clears it.

Needs `pfctl` (macOS, standard) or `nft` (Linux — installed by default on
most current distros; `pacman -S nftables` on Arch/Artix if missing).
Not yet available on Windows (needs the Windows Filtering Platform, a
much bigger lift).

**If your tunnel's config has no `DNS =` line**, wg-tray warns you before
enabling the kill switch: since nothing tells `wg-quick` to redirect DNS
to the tunnel, blocking DNS on your physical network will break name
resolution entirely rather than protect anything — there's no tunnel
DNS path for the block to be "instead of." Add a `DNS =` line via
**Edit config…** first if you want the kill switch and working DNS
together.

On Linux specifically, if you do have `DNS =` set but resolution still
doesn't switch to it, check whether `resolvconf`/`openresolv` is
actually applying updates: `resolvconf -u` clears a "signature mismatch"
error (something else touched `/etc/resolv.conf` since resolvconf last
wrote it) that silently prevents `wg-quick` from updating your resolver
even though it looks like nothing went wrong.

## Update checking and installing

wg-tray never phones home on its own. There's no background process, no
bundled analytics SDK, and no network request runs unless you trigger it
or explicitly opt in:

- **Settings → Check for updates now**: a single, one-off, unauthenticated
  GET to GitHub's public releases API (`api.github.com`) — the same request
  your browser makes if you open the Releases page yourself. No account,
  hardware ID, or usage data is attached.
- **Settings → Automatically check for updates**: an opt-in toggle,
  **off by default**. When enabled, it repeats that same check every few
  hours and shows a tray notification if a newer version exists. Turning it
  on doesn't change what's sent — same anonymous request, just on a timer.

Finding an update doesn't install anything by itself — that's a separate,
explicit step:

- **Settings → Install vX.Y.Z…**: downloads the right build for your OS
  and installs it in place, then quits and relaunches wg-tray on the new
  version. Shows a confirmation dialog first. Mechanics differ per OS
  since there's no universal "replace this app" primitive:
  - **Windows**: runs the downloaded Inno Setup installer silently, then quits.
  - **macOS**: mounts the downloaded `.dmg`, swaps the new `.app` in at the
    current install path, unmounts, relaunches.
  - **Linux**: replaces the running AppImage file in place with the
    downloaded one, then relaunches it.
  - Only available in packaged builds — running from source shows the
    new version number and tells you to `git pull` instead.

Auto-installing (downloading and running something unattended, no matter
how it got triggered) never happens — even with automatic checking
enabled, actually installing always needs you to click "Install" and
confirm the dialog.

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
