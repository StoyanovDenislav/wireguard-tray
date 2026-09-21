# Changelog

## 0.9.1

- **Fixed**: connecting with the kill switch enabled failed on every
  attempt after the first with "'<name>' looks like an already-derived
  leak-protection config." The guard against protecting an
  already-derived config's own name checked `name in
  _load_manifest().values()` — but `.values()` holds the *original*
  tunnel names, which every successfully-protected tunnel legitimately
  appears in after its first connect. This made the guard fire on every
  reconnect after the first one, not just the actual bad case it was
  meant to catch. Now checks manifest *keys* (the derived stems)
  instead, which is what "is this name itself a derived config"
  actually means.
- **Fixed**: a failed connect/disconnect could pop up multiple stacked
  "Failed to..." dialogs that looked like the error dialog "looping"
  when you tried to close one (closing it just revealed the next one
  queued behind it). Root cause: the v0.9.0 threading change connected
  the toggle-finished signal to its handler fresh on every single
  toggle attempt without ever disconnecting the previous one, so after
  N toggles a failure would fire the handler (and its error dialog) N
  times. Connected once now, in `__init__`, instead of per-toggle.

## 0.9.0

- **Changed**: left-click on the tray icon now opens the window;
  right-click opens the menu. Previously both were bound to the same
  click via `setContextMenu`, so this needed splitting via
  `QSystemTrayIcon.activated`'s reason instead.
- **Fixed**: connecting/disconnecting could make the whole window
  disappear entirely (had to reopen it from the tray). Root cause:
  `connect()`/`disconnect()` block on `subprocess.run()` while the
  pkexec/osascript/UAC privilege prompt is up, with nothing pumping the
  Qt event loop in the meantime — an unresponsive GUI app during an
  external elevation dialog can get its window hidden by the window
  manager. Connect/disconnect now run on a background QThread so the UI
  stays responsive throughout; the toggle button shows "Connecting…"/
  "Disconnecting…" and is disabled until it finishes.
- **Fixed**: a real cross-thread Qt violation introduced while building
  the above ("Cannot create children for a parent that is in a
  different thread") — WgTray is a plain Python object, not a QObject,
  so connecting the worker thread's finished signal directly to one of
  its methods gave Qt no thread context to route the call through
  safely. Routed through a signal on MainWindow (a real QObject with
  main-thread affinity) instead.
- **Fixed**: the connect button could silently stop responding after
  toggling the kill switch checkbox, only working again after
  unchecking and rechecking it. Root cause: an exception from
  `leak_protection.generate_protected_config()` (e.g. its
  already-derived-name guard) was propagating uncaught out of
  `connect()`, through a bare Qt signal handler that swallows it
  silently — the button looked fine but nothing happened. connect() now
  catches and surfaces this as a normal error message instead.
- **Added**: on Windows, the in-app updater's silent install
  (`/VERYSILENT`) now relaunches wg-tray afterward. The installer's
  post-install launch step previously had `skipifsilent`, which (by
  design, for a normal silent unattended install) skipped relaunching —
  but the in-app updater's whole premise is that the app quit and
  expects to come back up automatically. Not yet verified on a real
  Windows build.

## 0.8.1

- **Added**: a warning when enabling the kill switch on a tunnel with no
  `DNS =` line configured. Confirmed on real Linux testing: without a
  DNS server set, nothing tells wg-quick to redirect DNS to the tunnel,
  so the kill switch's DNS-block rule breaks name resolution entirely
  rather than protecting anything — the block has no tunnel DNS path to
  be "instead of." Documented the fix (add `DNS =` via the config
  editor) and, on Linux, a separate `resolvconf` "signature mismatch"
  gotcha that can silently prevent DNS from switching to the tunnel
  even with `DNS =` correctly set (`resolvconf -u` clears it).

## 0.8.0

- **Added**: kill switch + leak protection now works on Linux, not just
  macOS. Uses nftables (blocks all physical interfaces except DHCP and
  the WireGuard endpoint's port, blocks outbound DNS, passes the tunnel
  interface) and sysctl for the IPv6 guard — both are kernel/firewall
  level, so this works identically regardless of init system
  (systemd, runit, OpenRC, s6, dinit — including Artix's non-systemd
  variants) and never touches DNS resolver configuration
  (systemd-resolved/NetworkManager/resolv.conf), sidestepping the need
  to detect or support any of them specifically. Same opt-in,
  off-by-default checkbox and confirmation dialog as macOS.
  `leak_protection.is_supported()` now checks for `pfctl` (macOS) or
  `nft` (Linux) rather than assuming macOS.

## 0.7.0

- **Added**: a config editor for tweaking a tunnel's .conf directly —
  "Edit config…" in the tunnel detail pane. Two modes, switchable
  without losing edits: a structured form for the common fields
  (PrivateKey, Address, DNS, ListenPort, MTU, PublicKey, PresharedKey,
  Endpoint, AllowedIPs, PersistentKeepalive) that leaves everything
  else in the file untouched, and a raw-text mode for anything the form
  doesn't cover. Validates on save (both sections present, the fields
  wg-quick actually needs to bring the tunnel up) before writing.
  Disabled while the tunnel is connected.

## 0.6.1

- **Fixed**: enabling the kill switch could fail to connect at all, with
  wg-quick tearing the interface back down right after running the
  PostUp hook and no visible error. Root cause: `leak_protection_macos.sh`
  runs under `set -euo pipefail`, and its IPv6-snapshot step piped
  `networksetup -getinfo "$service"` into `awk` without guarding the
  pipeline's exit status — on a Mac with an unconfigured Thunderbolt
  port (a real hardware port `networksetup -listallhardwareports` lists,
  but not one `-getinfo` recognizes as an actual network service), that
  command fails, `pipefail` propagates it, and `set -e` aborts the
  entire script before it ever reaches the actual pf kill-switch step.
  Also stopped silencing the pf anchor load's own stderr, so a genuine
  kill-switch failure is visible in wg-quick's output instead of being
  thrown away.

## 0.6.0

- **Added**: detection of another VPN/tunnel already holding the default
  route before connecting (Linux/macOS). wg-quick picks the first
  "default" line from the routing table as the gateway for the
  WireGuard endpoint's own route — if another VPN's tunnel interface is
  in that slot instead of a real gateway IP, it fails with a cryptic
  `route: bad address: utunN`. wg-tray now checks for this up front and
  shows a dialog naming the likely cause (recognizing Mullvad,
  Tailscale, NordVPN, OpenVPN Connect, ExpressVPN, and Proton VPN
  daemons by process name), with a "Disconnect X" button for VPNs that
  have a well-known, official CLI disconnect command (Mullvad,
  Tailscale) — anything else is just named, not guessed at. "Connect
  anyway" is always available too.

## 0.5.2

- **Fixed**: enabling the kill switch failed with `wg-quick: The config
  file must be a valid interface name, followed by .conf` for almost any
  real tunnel name. wg-quick derives the network interface name from the
  config file's basename and rejects anything over 15 characters (a
  Linux/BSD interface-name limit it enforces even on macOS) —
  `<name>.protected.conf` blew past that for any tunnel name of 7+
  characters (e.g. "client1.protected" is already 17). Derived configs
  now use a short, deterministic name (`wgtp<hash>.conf`, always 14
  characters) instead, with a small manifest file mapping it back to the
  original tunnel name for the sidebar-filtering and lookup logic.

## 0.5.1

- **Fixed**: the v0.5.0 GitHub Release shipped with no platform binaries
  attached — only the auto-generated source zip/tar.gz. The release
  job's `actions/checkout` step ran *after* the built artifacts were
  downloaded and flattened into `release/`, and `checkout` cleans
  untracked files from the workspace before checking out, wiping that
  directory right before it was used to attach files to the release.
  Reordered so checkout runs first.

## 0.5.0

- **Added**: actual in-app update installation, not just a link to the
  Releases page. Settings now shows "Install vX.Y.Z…" when an update is
  found — it downloads the right build for your OS, installs it in
  place, and relaunches wg-tray on the new version. Windows runs the
  installer silently; macOS mounts the `.dmg` and swaps the `.app` in;
  Linux replaces the running AppImage file. Confirmed with a dialog
  first, and only ever runs when you click it — even with automatic
  update *checking* enabled, installing is always a separate, explicit
  step. Only available in packaged builds (running from source shows
  the version and tells you to `git pull`).

## 0.4.3

- **Fixed**: leak protection's derived `<name>.protected.conf` files live
  in the same directory as real tunnel configs, and were showing up as
  their own selectable "tunnels" in the sidebar. Enabling the kill
  switch on one of those created `<name>.protected.protected.conf`, and
  so on — a runaway cascade with no way to disable it once triggered.
  `list_configs()` now filters out derived configs, and
  `generate_protected_config()` refuses to run on a name that's already
  a derived config as a second line of defense.

## 0.4.2

- **Fixed**: "Couldn't reach GitHub to check for updates" in packaged
  builds (AppImage/dmg/installer). PyInstaller-frozen apps don't ship
  the OS's CA trust store the normal way, so HTTPS certificate
  verification against `api.github.com` was silently failing and
  getting swallowed by the update checker's broad error handling.
  Now uses `certifi`'s bundled CA file explicitly for the update
  checker's requests, and PyInstaller is told to bundle it.

## 0.4.1

- **Changed**: leak-protection DNS handling now blocks port 53 on
  physical interfaces via the pf anchor instead of pinning DNS to the
  tunnel's resolver — pinning was fragile if the tunnel dropped
  mid-resolution (timeout against an unreachable resolver instead of a
  clean block).
- **Fixed**: the kill switch's pf anchor now covers every physical
  network interface (enumerated dynamically — Wi-Fi, built-in Ethernet,
  Thunderbolt bridges, USB dongles), not just `en0`. Machines with a
  secondary interface were previously only partially protected.
- **Fixed**: IPv6 settings could be left disabled permanently if wg-tray
  or the tunnel was force-quit while connected (PreDown never ran).
  Connecting any protected tunnel now detects a leftover snapshot from
  an unclean shutdown and restores IPv6 automatically first.
- **Added**: a confirmation dialog when first enabling the kill switch
  for a tunnel, explaining that it blocks all internet access (not just
  the VPN) if the tunnel drops — the checkbox's tooltip made this clear
  but was easy to miss.

## 0.4.0

- **Added**: opt-in kill switch + leak protection for macOS. Per-tunnel
  checkbox enables a `pf`-based kill switch (blocks the physical interface
  if the tunnel drops), DNS pinning to the tunnel's resolver, and an IPv6
  guard (disables IPv6 on the physical interface while connected, since
  most configs only route IPv4). Off by default; doesn't touch tunnels
  that don't opt in. Not yet available on Linux/Windows.

## 0.3.1

- **Fixed**: `scripts/export_icon.py` was still importing the old
  pre-refactor `wg_tray` module and broke the CI icon-export step on
  every platform after the 0.3.0 package split.

## 0.3.0

- **Changed**: split the single ~1050-line `wg_tray.py` into a `wgtray/`
  package (`platform_utils`, `paths`, `state`, `wireguard`, `updater`,
  `theme`, `ui/main_window`, `ui/dialogs`, `tray`, `app`), with
  `wg_tray.py` left as a thin entry point.
- **Fixed**: the app showing as "Python" instead of "wg-tray" in the OS —
  set `AppUserModelID` on Windows, `desktopFileName` on Linux (matching
  the AppImage's `.desktop`), and `CFBundleName` in the macOS bundle.
- **Added**: privacy-conscious update checker. Settings dialog with a
  manual "Check for updates now" button and an "Automatically check"
  toggle (off by default) — both only ever make a single unauthenticated
  GET to GitHub's public releases API, never auto-download or
  auto-install.
- **Added**: one-time "What's new" changelog screen shown after an
  update, sourced from that version's GitHub Release notes.
- **Fixed**: left-clicking the tray icon no longer also pops the window
  open — it now just shows the tray menu (Qt's default). The window
  opens once automatically at launch instead.

## 0.2.x and earlier

- Added a dark, Mullvad-style theme and a code-drawn two-node "tunnel"
  connection icon (green when connected, grey when not).
- Added a sidebar + detail main window (tunnel list, connect/disconnect,
  status) alongside the existing tray menu.
- Added Windows support: `wireguard.exe` tunnel-service backend and UAC
  elevation, since Windows has neither `wg-quick` nor `pkexec`/`osascript`.
- Added GitHub Actions CI: builds for macOS, Linux, and Windows on every
  push, and publishes a GitHub Release with platform installers
  (`.dmg`, AppImage, Inno Setup `.exe`) and archives (`.zip`, `.tar.gz`)
  when a version tag is pushed.
