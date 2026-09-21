# Known issues

## Kill switch: connect fails/tears down when leak protection is enabled

**Status:** open, unresolved as of v0.6.0.

**Symptom:** connecting a tunnel with "Kill switch + leak protection"
enabled fails. wg-quick's log shows the interface coming up successfully
(routes added, DNS pinned, endpoint route added with a correct gateway —
no other-VPN conflict this time), then runs our PostUp hook
(`leak_protection_macos.sh up <port>`), and immediately after that the
log jumps to teardown (`rm -f .../utun4.sock`, `route -q -n delete
...`) with no visible output or error from the script itself in between.

Example failing log (this run had no conflicting VPN — gateway was a
real IP, `192.168.50.1`):

```
[#] route -q -n add -inet 109.120.214.185 -gateway 192.168.50.1
[#] networksetup -getdnsservers Thunderbolt Bridge
...
[#] /Users/denislav/.config/wg-tray/leak_protection_macos.sh up 51820
[#] rm -f /var/run/wireguard/utun4.sock
[#] rm -f /var/run/wireguard/wgtp1917e33407.name
[#] route -q -n delete -inet 109.120.214.185 (4)
```

**What this suggests:** `wg-quick` runs `PostUp` and treats a non-zero
exit code from it as fatal — it tears down the whole interface if
PostUp fails. So `leak_protection_macos.sh up 51820` is very likely
exiting non-zero, but wg-quick's `execution error: ...` wrapper (this is
being run via `osascript "do shell script ... with administrator
privileges"`, see `platform_utils.run_privileged`) doesn't appear to be
capturing/surfacing the script's actual stderr in the error shown to
the user — we're only seeing wg-quick's own trace, not why the script
failed.

**Where to look first:**
- `wgtray/resources/leak_protection_macos.sh`'s `do_up()` — it uses
  `set -euo pipefail` (added in the 0.4.1 hardening pass), so *any*
  failing command in it (a `pfctl` call, `networksetup`, the interface
  enumeration awk pipeline, etc.) will abort the whole script non-zero.
  Test it standalone as root first:
  ```
  sudo /Users/denislav/.config/wg-tray/leak_protection_macos.sh up 51820; echo "exit: $?"
  ```
  to see the actual failure without wg-quick/osascript swallowing it.
- Likely suspects given `set -e`: `pfctl -a ... -f ...` failing if pf
  isn't enabled by default on this system, or a `networksetup` call
  failing on an interface/service that doesn't accept it (e.g. the
  "Thunderbolt Bridge" service seen in the log — does `-setv6off` work
  on that service name, or does it error for non-network-carrying
  pseudo-interfaces like a Thunderbolt Bridge?).
- Once the real failing command is found, either fix that command's
  handling for this environment, or stop using `set -e` wholesale and
  handle failures per-command with explicit `|| true` / error checks
  (some of `do_up()`'s steps are genuinely best-effort and shouldn't be
  fatal — e.g. IPv6-off failing on one interface shouldn't block the pf
  anchor from loading).
- Separately: `run_privileged`'s osascript path only returns combined
  stdout+stderr from the *outer* `do shell script`, which is wg-quick's
  own output — the PostUp subprocess's stderr may not be propagating up
  cleanly through wg-quick's own error handling either. Worth checking
  what wg-quick itself prints when PostUp fails vs. what we're actually
  capturing.

**Repro state:** `client1` tunnel (a home config), leak protection
enabled, no other VPN active this time (ruled out the v0.6.0 conflict
scenario). Fails consistently as of this report.
