import argparse
import csv
import glob
import os
import re
from datetime import datetime

from analysis.eval_common import CLASSIFIERS, find_results


# usage: eval_timing.py [-h] [--run TS] [--live PATH [PATH ...]]

# Two latency metrics, averaged across sweeps:
#   1. Full-sweep duration
#   2. Plateau → video

# Modes:
#   default      — dataset replay runs (one events.log per IQ folder)
#   --live PATH  — live HackRF runs

TS_RE      = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)")
FREQ_RE    = re.compile(r"freq=([0-9.eE+\-]+)")
PLAT_RE    = re.compile(r"PLATEAU_CONFIRMED")
VIDEO_RE   = re.compile(r"VIDEO_CONFIRMED")

SWEEP_BREAK_HZ = 100_000_000

def parse_events(path):
    with open(path) as f:
        for line in f:
            tm = TS_RE.match(line)
            if not tm:
                continue
            ts = datetime.fromisoformat(tm.group(1))

            kind = None
            if PLAT_RE.search(line):
                kind = "plateau"
            elif VIDEO_RE.search(line):
                kind = "video"

            fm = FREQ_RE.search(line)
            freq_str = fm.group(1) if fm else None
            freq_hz  = float(freq_str) if freq_str else None

            yield ts, freq_str, freq_hz, kind


def split_sweeps(events):
    sweeps = []
    cur    = []
    prev_freq = None

    for ts, freq_str, freq_hz, kind in events:
        if (freq_hz is not None and prev_freq is not None
                and freq_hz + SWEEP_BREAK_HZ < prev_freq):
            sweeps.append(cur)
            cur = []
        cur.append((ts, freq_str, kind))
        if freq_hz is not None:
            prev_freq = freq_hz

    if cur:
        sweeps.append(cur)

    out = []
    for s in sweeps:
        if not s:
            continue
        out.append((s[0][0], s[-1][0], s))
    return out


def compute_metrics(sweep_groups):
    durations = []
    latencies = []

    for first_ts, last_ts, events in sweep_groups:
        durations.append((last_ts - first_ts).total_seconds())

        plateau_at = {}
        for ts, freq_str, kind in events:
            if freq_str is None:
                continue
            if kind == "plateau":
                plateau_at[freq_str] = ts
            elif kind == "video" and freq_str in plateau_at:
                latencies.append((ts - plateau_at[freq_str]).total_seconds() * 1000.0)

    return durations, latencies


def collect_dataset(run):
    paths = find_results(run=run)
    if not paths:
        raise SystemExit("[ERROR] no results CSVs found")

    out = {}
    for cls in CLASSIFIERS:
        if cls not in paths:
            continue
        results_csv = paths[cls]
        run_prefix  = os.path.basename(results_csv).replace("_results.csv", "")
        logs_dir    = os.path.dirname(results_csv)

        files = []
        with open(results_csv, newline="") as f:
            for row in csv.DictReader(f):
                p = os.path.join(logs_dir, f"{run_prefix}_{row['iq_folder']}", "events.log")
                if os.path.exists(p):
                    files.append(p)
        out[cls] = files
    return out


def collect_live(patterns):
    files = []
    for pat in patterns:
        if os.path.isdir(pat):
            cand = os.path.join(pat, "events.log")
            if os.path.exists(cand):
                files.append(cand)
            continue
        for p in sorted(glob.glob(pat)):
            cand = p if p.endswith("events.log") else os.path.join(p, "events.log")
            if os.path.exists(cand):
                files.append(cand)

    if not files:
        raise SystemExit(f"[ERROR] no events.log found under {patterns!r}")

    return {"live": files}


def _stats(xs):
    if not xs:
        return float("nan"), float("nan"), 0
    return sum(xs) / len(xs), max(xs), len(xs)


parser = argparse.ArgumentParser(description="Sweep duration and plateau→video latency")
parser.add_argument("--run", metavar="TS", help="Dataset run timestamp (default: latest)")
parser.add_argument("--live", nargs="+", metavar="PATH",
                    help="One or more live log dirs or globs (e.g. 'logs/myrun_*')")
parser.add_argument("--max-sweep-s", type=float, metavar="S",
                    help="Drop sweeps with duration above S seconds (filters paused/stalled runs)")
args = parser.parse_args()

if args.live:
    sources = collect_live(args.live)
else:
    sources = collect_dataset(args.run)


print(f"{'label':<14}  "
      f"{'sweep n':>7} {'mean (s)':>9} {'max (s)':>8}    "
      f"{'pv n':>5} {'mean (ms)':>10} {'max (ms)':>9}")
print("-" * 70)

all_durs, all_lats = [], []

dropped = 0
for label, files in sources.items():
    durs, lats = [], []
    for path in files:
        sweeps = split_sweeps(parse_events(path))
        d, l = compute_metrics(sweeps)
        if args.max_sweep_s is not None:
            kept = [x for x in d if x <= args.max_sweep_s]
            dropped += len(d) - len(kept)
            d = kept
        durs.extend(d)
        lats.extend(l)

    all_durs.extend(durs)
    all_lats.extend(lats)

    sm, sx, sn = _stats(durs)
    lm, lx, ln = _stats(lats)
    print(f"{label:<14}  {sn:>7d} {sm:>9.2f} {sx:>8.2f}    "
          f"{ln:>5d} {lm:>10.2f} {lx:>9.2f}")

if len(sources) > 1:
    sm, sx, sn = _stats(all_durs)
    lm, lx, ln = _stats(all_lats)
    print("-" * 70)
    print(f"{'pooled':<14}  {sn:>7d} {sm:>9.2f} {sx:>8.2f}    "
          f"{ln:>5d} {lm:>10.2f} {lx:>9.2f}")

print()
print("  sweep n     = number of sweeps timed")
print("  sweep mean  = mean wall time from first to last events.log entry within a sweep")
print("  pv n        = PLATEAU_CONFIRMED → VIDEO_CONFIRMED pairs found")
print("  pv mean     = mean ms from PLATEAU_CONFIRMED to VIDEO_CONFIRMED at the same freq")
if args.live:
    print(f"  sweep boundary = freq backwards jump > {SWEEP_BREAK_HZ/1e6:.0f} MHz")
if args.max_sweep_s is not None:
    print(f"  dropped {dropped} sweep(s) with duration > {args.max_sweep_s:.1f} s")
