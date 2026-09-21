# Changelog

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
