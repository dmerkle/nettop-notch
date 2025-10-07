#!/usr/bin/env python3
"""
nettop-notch — interactive macOS nettop rate viewer (Δ/Σ KB/s per process)
"""
import argparse, csv, shutil, subprocess, time, sys, os
from datetime import datetime
from . import __version__

# =========================
# Config / Defaults
# =========================
DEFAULT_INTERVAL = 3.0
DEFAULT_TOP = 20
DEFAULT_THRESHOLD_KBS = 500.0  # KB/s (highlight threshold; 0 disables)
NUMW = 11  # width for numeric columns

# ANSI (used only in non-UI mode)
RESET = "\033[0m"; BOLD = "\033[1m"; GREEN = "\033[92m"; HILITE = GREEN + BOLD

def _is_macos() -> bool:
    return sys.platform == "darwin"

def _ensure_macos_or_exit():
    if not _is_macos():
        print("nettop-notch benötigt macOS (ruft das eingebaute `nettop` auf).", file=sys.stderr)
        sys.exit(1)
    # `nettop` prüfen
    from shutil import which
    if which("nettop") is None:
        print("`nettop` wurde nicht gefunden. Ist es in PATH? (macOS enthält es standardmäßig.)", file=sys.stderr)
        sys.exit(1)

# =========================
# nettop plumbing
# =========================
def build_nettop_cmd(nettop_args):
    cmd = ["nettop"]
    if nettop_args: cmd += nettop_args
    flat = " ".join(cmd).lower()
    if "-n" not in flat.split(): cmd += ["-n"]             # no DNS
    if "-x" not in flat.split(): cmd += ["-x"]             # CSV
    if "-l" not in flat and "-L" not in flat: cmd += ["-L","1"]  # one sample per call
    return cmd

def run_csv(cmd):
    try:
        out = subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError:
        return [], []
    except Exception:
        return [], []
    rows = list(csv.reader(out.splitlines()))
    if not rows: return [], []
    header = rows[0]
    if len(header)>1 and (header[1]=="" or header[1].lower()=="process"):
        header[1] = "process"
    return header, rows[1:]

def parse_snapshot(cmd):
    """
    Returns:
      proc_totals: dict proc -> (bytes_in, bytes_out)
      proc_conns:  dict proc -> list of {'iface','state','local','remote'}
    """
    header, body = run_csv(cmd)
    if not header: return {}, {}
    idx = {name.lower(): i for i,name in enumerate(header)}
    col_iface = idx.get("interface")
    col_state = idx.get("state")
    col_in    = idx.get("bytes_in")
    col_out   = idx.get("bytes_out")

    proc_totals, proc_conns = {}, {}
    cur_proc = None

    for r in body:
        cell1 = r[1].strip() if len(r)>1 else ""
        iface = r[col_iface].strip() if col_iface is not None and col_iface < len(r) else ""
        state = r[col_state].strip() if col_state is not None and col_state < len(r) else ""

        is_conn = "<->" in cell1 or cell1.startswith(("tcp","udp"))
        if is_conn:
            if cur_proc:
                parts = cell1.split("<->", 1)
                local = parts[0].strip() if parts else ""
                remote = parts[1].strip() if len(parts) > 1 else ""
                proc_conns.setdefault(cur_proc, []).append({
                    "iface": (iface or "-"), "state": (state or "-"),
                    "local": local, "remote": remote
                })
            continue

        proc = cell1
        if not proc: continue
        cur_proc = proc
        try:
            bin_  = int(r[col_in])  if col_in  is not None and r[col_in]  else 0
            bout_ = int(r[col_out]) if col_out is not None and r[col_out] else 0
        except Exception:
            bin_, bout_ = 0, 0
        proc_totals[proc] = (bin_, bout_)
        proc_conns.setdefault(proc, [])

    return proc_totals, proc_conns

# =========================
# helpers / formatting
# =========================
def kbs_num(n_bytes_per_sec):
    return f"{(n_bytes_per_sec/1024.0):{NUMW}.1f}"

def clear():
    print("\033[H\033[J", end="")

# ---------- Interface prioritization ----------
def summarize_ifaces(conns):
    """
    Returns (primary_iface, extra_count, state_for_primary).
    - Prefer real interfaces over '-' and loopback.
    - extra_count counts distinct real interfaces (includes lo0), ignores '-'.
    """
    if not conns:
        return "-", 0, "-"

    seen = {}
    for c in conns:
        i = (c.get("iface") or "-")
        if i not in seen:
            seen[i] = None
    uniq = list(seen.keys())

    placeholder = {"-"}
    loopbacks = {"lo", "lo0"}
    real_ifaces = [i for i in uniq if i not in placeholder]
    externals   = [i for i in real_ifaces if i not in loopbacks]

    def score(i: str) -> int:
        if i in placeholder: return -100
        n = i.lower()
        if n.startswith("en"):      return 100   # Ethernet/Wi-Fi
        if n.startswith("pdp_ip"):  return 90
        if n.startswith("utun"):    return 80    # VPN
        if n.startswith("awdl"):    return 40
        if n in loopbacks:          return -10
        return 50

    candidates = externals or real_ifaces or ["-"]
    primary = max(candidates, key=lambda i: (score(i), i))
    extra_real = len(set(real_ifaces)) - 1 if real_ifaces else 0

    state = next((c.get("state","-") for c in conns if (c.get("iface") or "-") == primary),
                 conns[0].get("state","-"))
    return primary, max(0, extra_real), state

# =========================
# rows building (metrics, with dt)
# =========================
def build_rows(group, prev_totals, curr_totals, curr_conns, dt_seconds):
    """
    Compute per-process rates and build rows.
    Each row has rin, rout, rsum, rdelta regardless of which is displayed.
    Rates are based on actual elapsed time dt_seconds.
    """
    if dt_seconds <= 0:
        dt_seconds = 1e-6

    proc_rate = {}
    for proc, (bin_now, bout_now) in curr_totals.items():
        bin_prev, bout_prev = prev_totals.get(proc, (bin_now, bout_now))
        din  = max(0, bin_now  - bin_prev)
        dout = max(0, bout_now - bout_prev)
        if din or dout:
            rin  = din  / dt_seconds
            rout = dout / dt_seconds
            rsum = rin + rout
            rdelta = abs(rin - rout)
            proc_rate[proc] = (rin, rout, rsum, rdelta)

    rows = []
    if group == "remote":
        grouped = {}
        for proc, conns in curr_conns.items():
            if proc not in proc_rate: continue
            rin, rout, rsum, rdelta = proc_rate[proc]
            for c in conns:
                key = (proc, c["iface"], c["state"], c["remote"])
                e = grouped.get(key)
                if not e:
                    grouped[key] = {
                        "proc": proc, "iface": c["iface"], "state": c["state"],
                        "remote": c["remote"], "locals": [c["local"]],
                        "rin": rin, "rout": rout, "rsum": rsum, "rdelta": rdelta
                    }
                else:
                    e["locals"].append(c["local"])
        rows = list(grouped.values())
    else:
        for proc, (rin, rout, rsum, rdelta) in proc_rate.items():
            conns = curr_conns.get(proc, [])
            remotes = [c["remote"] for c in conns if c["remote"]]
            sockets = len(conns)
            distinct_remotes = len(set(remotes))
            first_remote = remotes[0] if remotes else "(no remote)"
            extra = ""
            if distinct_remotes > 1 or sockets > 1:
                extra = f"  [+{max(0,distinct_remotes-1)} remotes, +{max(0,sockets-1)} sockets]"
            primary_iface, extra_ifaces, state_for_primary = summarize_ifaces(conns)
            iface_disp = primary_iface if extra_ifaces <= 0 else f"{primary_iface} (+{extra_ifaces})"
            rows.append({
                "proc": proc, "iface": iface_disp, "state": state_for_primary,
                "conn": first_remote + extra,
                "rin": rin, "rout": rout, "rsum": rsum, "rdelta": rdelta
            })
    return rows

# =========================
# curses UI
# =========================
def ui_loop(args, cmd):
    import curses

    # --- UI State ---
    display_metric = "delta"   # column shown: 'delta' or 'sum' (default delta)
    sort_key = "delta"         # 'in' | 'out' | 'delta' (default delta)
    show_help = True

    # warm-up snapshot & time anchor
    prev_totals, _ = parse_snapshot(cmd)
    prev_time = time.monotonic()

    def header_lines(width):
        metric_label = "Δ = |IN-OUT|" if display_metric == "delta" else "SUM = IN+OUT"
        sort_name = {"in":"IN", "out":"OUT", "delta":"Δ = |IN-OUT|"}[sort_key]
        return [
            f" nettop rates watch  [{datetime.now().isoformat(timespec='seconds')}]  interval={args.interval:.1f}s  group={args.group}  threshold={args.threshold:.1f} KB/s",
            f" cmd: {' '.join(cmd)}",
            f" keys: [h] help  [i] sort IN  [o] sort OUT  [d] sort Δ  [m] toggle column (Δ↔SUM)  [t] change interval  [q] quit",
            f" column: {metric_label}   sorting by: {sort_name}"
        ]

    def setup_colors(stdscr):
        curses.start_color()
        # Background mode selection
        if args.bg == "default":
            try:
                curses.use_default_colors()
            except Exception:
                pass
            bg = -1
        elif args.bg == "trueblack":
            if curses.can_change_color():
                try:
                    curses.init_color(curses.COLOR_BLACK, 0, 0, 0)
                except Exception:
                    pass
            bg = curses.COLOR_BLACK
        else:  # "black" (ANSI black)
            bg = curses.COLOR_BLACK

        curses.init_pair(1, curses.COLOR_WHITE, bg)   # normal
        curses.init_pair(2, curses.COLOR_GREEN, bg)   # highlight
        normal_attr = curses.color_pair(1)
        hilite_attr = curses.color_pair(2)

        stdscr.bkgd(' ', normal_attr)
        stdscr.attrset(normal_attr)
        return normal_attr, hilite_attr

    def draw(stdscr, rows, normal_attr, hilite_attr):
        stdscr.erase()
        maxy, maxx = stdscr.getmaxyx()

        # hard fill
        for y in range(maxy):
            stdscr.addnstr(y, 0, " " * (maxx - 1), maxx - 1, normal_attr)

        top = 0
        if show_help:
            for ln in header_lines(maxx):
                stdscr.addnstr(top, 0, ln.ljust(maxx-1), maxx-1, normal_attr); top += 1
            stdscr.addnstr(top, 0, ("-" * (maxx-1)), maxx-1, normal_attr); top += 1

        metric_hdr = "Δ KB/s" if display_metric == "delta" else "SUM KB/s"
        hdr = (f"{'IN KB/s':>{NUMW}}  {'OUT KB/s':>{NUMW}}  "
               f"{metric_hdr:>{NUMW}}   "
               f"{'PROCESS':<30}  {'IFACE(S)':<12}  {'STATE':<12}  CONNECTION")
        stdscr.addnstr(top, 0, hdr.ljust(maxx-1), maxx-1, normal_attr); top += 1
        stdscr.addnstr(top, 0, ("-" * (maxx-1)), maxx-1, normal_attr); top += 1

        shown = 0
        thr_bytes = args.threshold * 1024.0
        for e in rows:
            if shown >= args.top or top >= maxy-1: break
            rin, rout = e["rin"], e["rout"]
            metric_val = e["rdelta"] if display_metric=="delta" else e["rsum"]
            proc = e["proc"]; iface = e.get("iface","-"); state = e.get("state","-")
            if args.group == "remote":
                locals_list = e.get("locals") or []
                first_local = locals_list[0] if locals_list else None
                extra = f" [+{len(locals_list)-1}]" if len(locals_list) > 1 else ""
                conn_str = (first_local + "<->" if first_local else "") + e["remote"] + extra
            else:
                conn_str = e["conn"]

            line = (
                f"{kbs_num(rin):>{NUMW}}  {kbs_num(rout):>{NUMW}}  {kbs_num(metric_val):>{NUMW}}   "
                f"{proc:<30}  {iface:<12}  {state:<12}  {conn_str}"
            )

            attr = hilite_attr if (thr_bytes > 0 and metric_val > thr_bytes) else normal_attr
            stdscr.addnstr(top, 0, line.ljust(maxx-1), maxx-1, attr)
            top += 1; shown += 1

        if shown == 0 and top < maxy:
            stdscr.addnstr(top, 0, "(no process traffic this interval)".ljust(maxx-1), maxx-1, normal_attr)

        stdscr.refresh()

    def poll_key(stdscr, timeout_ms):
        stdscr.timeout(timeout_ms)
        try:
            ch = stdscr.getch()
        except KeyboardInterrupt:
            return "quit"
        if ch == -1:
            return None
        c = chr(ch).lower() if 0 <= ch < 256 else None
        if c == 'q': return "quit"
        if c == 'h': return "help"
        if c == 'i': return "sort_in"
        if c == 'o': return "sort_out"
        if c == 'd': return "sort_delta"
        if c == 'm': return "toggle_metric_column"
        if c == 't': return "change_interval"
        return None

    def prompt_interval_blocking(stdscr, normal_attr):
        maxy, maxx = stdscr.getmaxyx()
        prompt = "New interval (seconds, e.g., 0.5 or 2): "
        stdscr.addnstr(maxy-1, 0, " " * (maxx-1), maxx-1, normal_attr)
        stdscr.addnstr(maxy-1, 0, prompt, maxx-1, normal_attr)
        try: import curses; curses.curs_set(1)
        except Exception: pass
        curses.echo()
        stdscr.timeout(-1)
        try:
            s = stdscr.getstr(maxy-1, len(prompt), 32).decode("utf-8").strip()
        except Exception:
            s = ""
        finally:
            curses.noecho()
            try: curses.curs_set(0)
            except Exception: pass
        return s

    def loop(stdscr):
        nonlocal prev_totals, prev_time, display_metric, sort_key, show_help
        normal_attr, hilite_attr = setup_colors(stdscr)
        next_target = time.monotonic()

        while True:
            curr_totals, curr_conns = parse_snapshot(cmd)
            now = time.monotonic()
            dt = max(1e-6, now - prev_time)
            rows = build_rows(args.group, prev_totals, curr_totals, curr_conns, dt)
            prev_totals = curr_totals
            prev_time = now

            if sort_key == "in":
                rows.sort(key=lambda e: e["rin"], reverse=True)
            elif sort_key == "out":
                rows.sort(key=lambda e: e["rout"], reverse=True)
            else:
                rows.sort(key=lambda e: e["rdelta"], reverse=True)

            draw(stdscr, rows, normal_attr, hilite_attr)

            next_target += args.interval
            remaining = max(0.0, next_target - time.monotonic())
            ms = max(10, int(remaining * 1000))

            action = poll_key(stdscr, ms)
            if action == "quit": break
            elif action == "help": show_help = not show_help
            elif action == "sort_in": sort_key = "in"
            elif action == "sort_out": sort_key = "out"
            elif action == "sort_delta": sort_key = "delta"
            elif action == "toggle_metric_column":
                display_metric = "sum" if display_metric == "delta" else "delta"
            elif action == "change_interval":
                s = prompt_interval_blocking(stdscr, normal_attr)
                if s:
                    try:
                        val = float(s)
                        if val > 0:
                            args.interval = val
                    except ValueError:
                        pass
                next_target = time.monotonic()

    import curses
    curses.wrapper(loop)

# =========================
# non-UI fallback (stdout)
# =========================
def non_ui_loop(args, cmd):
    prev_totals, _ = parse_snapshot(cmd)
    prev_time = time.monotonic()

    display_metric = "delta"
    sort_key = "delta"
    thr_bytes = args.threshold * 1024.0

    try:
        next_target = time.monotonic()
        while True:
            curr_totals, curr_conns = parse_snapshot(cmd)
            now = time.monotonic()
            dt = max(1e-6, now - prev_time)
            rows = build_rows(args.group, prev_totals, curr_totals, curr_conns, dt)
            prev_totals = curr_totals
            prev_time = now

            if sort_key == "in":
                rows.sort(key=lambda e: e["rin"], reverse=True)
            elif sort_key == "out":
                rows.sort(key=lambda e: e["rout"], reverse=True)
            else:
                rows.sort(key=lambda e: e["rdelta"], reverse=True)

            clear()
            width = shutil.get_terminal_size((150, 26)).columns
            line = "-" * width
            print(line)
            print(f" nettop rates watch  [{datetime.now().isoformat(timespec='seconds')}]  interval={args.interval:.1f}s  group={args.group}  threshold={args.threshold:.1f} KB/s")
            print(f" cmd: {' '.join(cmd)}")
            print(" (non-UI fallback) Run in a real TTY for interactive keys: h i o d m t q")
            print(line)

            metric_hdr = "Δ KB/s" if display_metric == "delta" else "SUM KB/s"
            print(f"{'IN KB/s':>{NUMW}}  {'OUT KB/s':>{NUMW}}  {metric_hdr:>{NUMW}}   "
                  f"{'PROCESS':<30}  {'IFACE(S)':<12}  {'STATE':<12}  CONNECTION")
            print(line)

            shown = 0
            for e in rows:
                if shown >= args.top: break
                rin, rout = e["rin"], e["rout"]
                metric_val = e["rdelta"] if display_metric=="delta" else e["rsum"]
                proc, iface, state = e["proc"], e.get("iface","-"), e.get("state","-")
                if args.group == "remote":
                    locals_list = e.get("locals") or []
                    first_local = locals_list[0] if locals_list else None
                    extra = f" [+{len(locals_list)-1}]" if len(locals_list) > 1 else ""
                    conn_str = (first_local + "<->" if first_local else "") + e["remote"] + extra
                else:
                    conn_str = e["conn"]

                use_hilite = (args.threshold > 0 and metric_val > thr_bytes)
                prefix = HILITE if use_hilite else ""
                suffix = RESET if use_hilite else ""
                line_str = (
                    f"{kbs_num(rin):>{NUMW}}  {kbs_num(rout):>{NUMW}}  {kbs_num(metric_val):>{NUMW}}   "
                    f"{proc:<30}  {iface:<12}  {state:<12}  {conn_str}"
                )
                print(prefix + line_str + suffix)
                shown += 1

            if shown == 0:
                print("(no process traffic this interval)")

            next_target += args.interval
            remaining = max(0.0, next_target - time.monotonic())
            time.sleep(remaining)
    except KeyboardInterrupt:
        print("\nExiting.")

# =========================
# main
# =========================
def main(argv=None):
    _ensure_macos_or_exit()

    ap = argparse.ArgumentParser(
        prog="nettop-notch",
        description="Watch nettop rates (bytes/sec per process) with connection listing & grouping."
    )
    ap.add_argument("-V","--version", action="version", version=f"nettop-notch {__version__}")
    ap.add_argument("-i","--interval", type=float, default=DEFAULT_INTERVAL, help=f"Sampling interval seconds (default {DEFAULT_INTERVAL})")
    ap.add_argument("-t","--top", type=int, default=DEFAULT_TOP, help=f"Top rows to show (default {DEFAULT_TOP})")
    ap.add_argument("-g","--group", choices=["remote","process"], default="process",
                    help='Grouping: "remote" = per (proc,iface,state,remote); "process" = one line per process')
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_KBS,
                    help=f"Highlight threshold in KB/s for displayed metric (default {DEFAULT_THRESHOLD_KBS}; 0 disables)")
    ap.add_argument("--bg", choices=["black","trueblack","default"], default="black",
                    help="Background: 'black' (ANSI black), 'trueblack' (RGB 0,0,0 if supported), or 'default' (terminal bg).")
    ap.add_argument("nettop_args", nargs=argparse.REMAINDER,
                    help='Args passed to nettop (put them after --). Example: -- -t wired -p ssh -m tcp')
    args = ap.parse_args(argv)

    nettop_args = args.nettop_args
    if nettop_args and nettop_args[0] == "--":
        nettop_args = nettop_args[1:]
    cmd = build_nettop_cmd(nettop_args)

    use_ui = sys.stdin.isatty() and sys.stdout.isatty() and os.environ.get("TERM")
    if use_ui:
        try:
            ui_loop(args, cmd)
            return 0
        except Exception as e:
            print(f"(UI disabled: {e})", file=sys.stderr)

    non_ui_loop(args, cmd)
    return 0

if __name__ == "__main__":
    sys.exit(main())

