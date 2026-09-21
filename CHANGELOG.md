# Changelog

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
