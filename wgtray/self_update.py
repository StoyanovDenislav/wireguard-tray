"""Downloads and installs an update in place, then relaunches the app.

Each platform gets a different install strategy because there's no
single "replace this app" primitive:

- Windows: run the Inno Setup installer .exe silently, then quit so it
  can overwrite files that were locked while wg-tray was running.
- macOS: mount the downloaded .dmg, copy the new .app over the current
  bundle's own path, unmount, relaunch the new copy, quit.
- Linux (AppImage): the running AppImage is a single file; download the
  new one, chmod +x, replace it at its own path, relaunch, quit.

This only ever runs when the user explicitly clicks "Install update" in
Settings — never automatically, matching the rest of the app's "nothing
happens without you clicking it" posture. Downloading and running an
installer is a meaningfully bigger trust step than the update *check*,
so it isn't gated by the same "automatically check" toggle.
"""
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from .platform_utils import IS_LINUX, IS_MAC, IS_WINDOWS
from .updater import _ssl_context

CHUNK_SIZE = 256 * 1024


class UpdateError(Exception):
    pass


def current_executable_path():
    """
    The running app's own binary/bundle path, i.e. what needs to be
    replaced. sys.executable is the frozen binary itself under
    PyInstaller (not the system Python interpreter, since PyInstaller
    embeds its own). Running from source (`python wg_tray.py`) has no
    sensible answer here — self-update isn't offered in that case.
    """
    return Path(sys.executable).resolve()


def is_frozen():
    return getattr(sys, "frozen", False)


def download(url, dest_path, on_progress=None):
    """
    Stream download url to dest_path. on_progress(bytes_done, bytes_total)
    is called periodically if given (bytes_total is 0 if the server
    didn't send Content-Length).
    """
    req = urllib.request.Request(url, headers={"User-Agent": "wg-tray"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as e:
        raise UpdateError(f"Download failed: {e}") from e


def install_and_relaunch(asset, on_progress=None):
    """
    Download `asset` (a dict from updater.asset_for_platform) and install
    it, then relaunch the new version and exit this process. Raises
    UpdateError with a user-facing message on any failure — nothing here
    should be allowed to half-apply an update silently.
    """
    if not is_frozen():
        raise UpdateError(
            "Self-update only works in a packaged build, not when running from source."
        )

    tmp_dir = Path(tempfile.mkdtemp(prefix="wg-tray-update-"))
    downloaded = tmp_dir / asset["name"]
    download(asset["download_url"], downloaded, on_progress)

    if IS_WINDOWS:
        _install_windows(downloaded)
    elif IS_MAC:
        _install_macos(downloaded)
    elif IS_LINUX:
        _install_linux_appimage(downloaded)
    else:
        raise UpdateError("Self-update isn't supported on this platform.")


def _install_windows(installer_exe):
    # /VERYSILENT: no UI. /SUPPRESSMSGBOXES: no "successful" popup.
    # /NORESTART: don't reboot Windows. The installer overwrites wg-tray's
    # files once this process exits (its own install dir isn't locked by
    # a process that's already quitting), so launch it detached and then
    # quit ourselves immediately after — see the module docstring.
    try:
        subprocess.Popen(
            [str(installer_exe), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as e:
        raise UpdateError(f"Couldn't launch the installer: {e}") from e
    os._exit(0)


def _install_macos(dmg_path):
    current_app = _find_current_app_bundle()
    if current_app is None:
        raise UpdateError(
            "Couldn't determine the current app's install location — "
            "update it manually from the .dmg instead."
        )

    mount_point = Path(tempfile.mkdtemp(prefix="wg-tray-mount-"))
    try:
        result = subprocess.run(
            ["hdiutil", "attach", str(dmg_path), "-mountpoint", str(mount_point), "-nobrowse", "-quiet"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise UpdateError(f"Couldn't mount the update image: {result.stderr.strip()}")

        new_app = next(mount_point.glob("*.app"), None)
        if new_app is None:
            raise UpdateError("The downloaded update image didn't contain an app.")

        # Replace the bundle at its current install path. This needs
        # write access to that path — if wg-tray is in /Applications and
        # the user isn't in the admins group, this can fail; the caller
        # surfaces that as an UpdateError rather than silently no-op'ing.
        tmp_old = current_app.parent / f".{current_app.name}.old-{os.getpid()}"
        try:
            shutil.move(str(current_app), str(tmp_old))
            shutil.copytree(str(new_app), str(current_app))
            shutil.rmtree(str(tmp_old), ignore_errors=True)
        except OSError as e:
            # Best-effort rollback so a failed update doesn't leave the
            # user with no app at all.
            if tmp_old.exists() and not current_app.exists():
                shutil.move(str(tmp_old), str(current_app))
            raise UpdateError(f"Couldn't replace the app bundle: {e}") from e
    finally:
        subprocess.run(["hdiutil", "detach", str(mount_point), "-quiet"], capture_output=True)
        shutil.rmtree(mount_point, ignore_errors=True)

    subprocess.Popen(["open", str(current_app)])
    os._exit(0)


def _find_current_app_bundle():
    """Walk up from the running binary to the containing .app, e.g.
    /Applications/wg-tray.app/Contents/MacOS/wg-tray -> /Applications/wg-tray.app."""
    for parent in current_executable_path().parents:
        if parent.suffix == ".app":
            return parent
    return None


def _install_linux_appimage(new_appimage):
    current = current_executable_path()
    # APPIMAGE env var (set by the AppImage runtime itself) is the most
    # reliable way to find the *mounted* AppImage's real on-disk path;
    # sys.executable can point inside the SquashFS mount instead of the
    # actual file on first glance, depending on the AppImage runtime.
    target = Path(os.environ.get("APPIMAGE", str(current))).resolve()

    try:
        shutil.copyfile(new_appimage, target)
        target.chmod(0o755)
    except OSError as e:
        raise UpdateError(f"Couldn't replace the AppImage at {target}: {e}") from e

    subprocess.Popen([str(target)])
    os._exit(0)
