# nettop-notch

Interactive, no-dependency viewer for macOS `nettop` **rates**  
( KB/s IN, OUT, **Δ = |IN-OUT|**, **Σ = IN+OUT** ) with a curses UI and a clean non-UI fallback.

- **No Python deps** (stdlib only)
- **macOS only** (uses the built-in `nettop`)
- Tested down to **macOS Catalina**

---

## Quick demo

Recommended first run (true black background, `nettop` filtered to external traffic):

```bash
nettop-notch --bg trueblack -- -t external


nettop rates watch  [2025-10-07T09:35:06]  interval=3.0s  group=process  threshold=500.0 KB/s
 cmd: nettop -t external -n -x -L 1
 keys: [h] help  [i] sort IN  [o] sort OUT  [d] sort Δ  [m] toggle column (Δ↔SUM)  [t] change interval  [q] quit
 column: Δ = |IN-OUT|   sorting by: Δ = |IN-OUT|
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
    IN KB/s     OUT KB/s       Δ KB/s   PROCESS                         IFACE(S)      STATE         CONNECTION
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
      396.4         30.4        366.0   obfs4proxy.69386                en0           SynSent       89.99.36.84:8042  [+2 remotes, +2 sockets]
        1.1          3.9          2.8   syncthing.22169                 en1 (+2)      SynSent       fdbd:a32:9401:d69c:cb0:84f3:62a8:9037.22000  [+18 remotes, +27 sockets]
        3.5          1.1          2.4   MSTeams.37922                   en0           Established   2613:1026:3000:c9::7.443  [+3 remotes, +4 sockets]
        1.3          2.1          0.8   IPNExtension.19512              en0           Established   2916:4700:4700::1111.443  [+6 remotes, +6 sockets]
        0.8          0.0          0.7   mDNSResponder.182               bridge101 (+1)  -             *.*  [+1 remotes, +1 sockets]
        0.2          0.0          0.2   Microsoft Outlo.12891           en0           Established   15.69.239.78:443  [+4 remotes, +4 sockets]
        0.2          0.0          0.1   Microsoft Teams.37952           en0           Established   2603:1064:20::1ba.443  [+2 remotes, +2 sockets]
        0.0          0.0          0.0   Discord Helper.17162            en0           Established   162.159.236.234:443
        0.0          0.0          0.0   apsd.133                        en0           Established   17.57.147.56:5223
        0.0          0.0          0.0   com.docker.back.10832           en0 (+1)      Established   *:*  [+1 remotes, +2 sockets]
        0.0          0.0          0.0   Google Chrome H.16829           en0           Established   2001:648:504:2040::37.443  [+2 remotes, +3 sockets]
        0.0          0.0          0.0   zoom.us.25935                   en0           Established   2407:31c0:182::aa72:3489.443  [+3 remotes, +3 sockets]
        0.0          0.0          0.0   firefox.50924                   en0           Established   2a06:99c1:3108::ac40:94eb.443  [+3 remotes, +3 sockets]
        0.0          0.0          0.0   firefox.50792                   en0           Established   34.108.243.93:443  [+1 remotes, +1 sockets]
```

---

## Features

* **Per-process** view or **per-remote** grouping (proc, iface, state, remote)
* Live metrics: **IN**, **OUT**, **Δ = |IN-OUT|**, **Σ = IN+OUT**
* Interactive **sorting** by IN / OUT / Δ
* Toggle displayed metric column (Δ ↔ Σ)
* Change sampling interval live
* Highlight threshold in KB/s
* Non-UI mode prints a clean table to stdout (good for logs/tmux)

---

## Requirements

* **macOS** (uses Apple’s built-in `nettop`)
* **Python 3.8+**
* Terminal that supports ANSI escapes (for best UI experience)

> Note: If you run it on non-macOS, it exits with a clear error.

---

## Installation

### Clone & run

```bash
git clone https://github.com/dmerkle/nettop-notch.git
cd nettop-notch
PYTHONPATH=src ./bin/nettop-notch --bg trueblack -- -t external
```

or

```
PYTHONPATH=src python3 -m nettop_notch.cli --bg trueblack -- -t external
```

---

## Usage

```bash
# Default (process view, Δ column, 3s interval, top 20)
nettop-notch

# External traffic focus, true black background
nettop-notch --bg trueblack -- -t external

# Remote grouping
nettop-notch -g remote

# Faster refresh, more rows, higher highlight threshold
nettop-notch -i 0.5 -t 30 --threshold 1000

# Pass filters through to `nettop` (everything after `--`):
nettop-notch -- -t wifi -m tcp
```

### UI keys

* `h` toggle help
* `i` sort by IN
* `o` sort by OUT
* `d` sort by Δ
* `m` toggle metric column (Δ ↔ Σ)
* `t` change interval (blocking prompt)
* `q` quit

---

## Exit codes

* `0` success
* `1` failed preconditions (non-macOS, `nettop` not found), or unhandled error before entering the main loop

---

## Tips & Notes

* Run inside a **real TTY** to get the interactive UI (curses). In pipes/redirects, it automatically switches to the non-UI mode.
* On older macOS (e.g., **Catalina**), `curses` is available by default; no extra libraries needed.
* If DNS lookups slow you down, note we call `nettop` with `-n` (no DNS) by default.
* For VPN traffic, `utun` interfaces are recognized and de-prioritized after physical interfaces when picking the primary interface label.

---

## Privacy

This tool **does not** send any data anywhere. It only invokes the local `nettop` command and renders its CSV output in your terminal.

---

## Contributing

This was meant for personal convenience only. Feel free to clone and reuse
Please keep:

* no external Python dependencies,
* responsive rendering in narrow/wide terminals,
* and non-UI output stable (useful for logs).

### Testing locally

```bash
# From repo root:
PYTHONPATH=src pytest -q
```

---

## License

MIT — see [LICENSE](LICENSE).


