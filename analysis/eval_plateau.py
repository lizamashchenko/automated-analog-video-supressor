import argparse
import csv
import os
import re

from analysis.eval_common import (
    CLASSIFIERS, find_results, load_meta, fmt_pct,
)


# usage: eval_plateau.py [-h] [--run TS] [--classifier {harmonic,cyclo,autocorr}]
#                       [--meta PATH] [--tolerance MHZ] [--scan-steps N]

# Plateau-detector metrics across the dataset:
#   1. Pd_plat   — fraction of drone-present sweeps with ≥1 confirmed plateau
#                  within ±tolerance of the labelled drone frequency
#   2. Pfa_plat  — mean confirmed plateaus per drone-absent sweep
#   3. reduction — 1 − mean(confirmed/sweep) / scan_steps
#                  (parameters reject most candidate frequencies outright)
#   4. voting    — rejected / (rejected + confirmed)
#                  (voting rejects candidates that had 1–2 hits but < required)


DEFAULT_META   = "/home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv"
DEFAULT_TOL_HZ = 5_000_000
DEFAULT_STEPS  = 295

CONF_RE = re.compile(r"PLATEAU_CONFIRMED.*?freq=([0-9.eE+\-]+)")
REJ_RE  = re.compile(r"PLATEAU_REJECTED.*?freq=([0-9.eE+\-]+)")

parser = argparse.ArgumentParser(description="Plateau-detector Pd / Pfa / reduction / voting-rejection metrics")
parser.add_argument("--run", metavar="TS", help="Run timestamp (default: latest)")
parser.add_argument("--classifier", default="harmonic", choices=CLASSIFIERS,
                    help="Which classifier run's events.log to parse (default: harmonic)")
parser.add_argument("--meta", metavar="PATH", default=DEFAULT_META,
                    help=f"Metadata CSV (default: {DEFAULT_META})")
parser.add_argument("--tolerance", type=float, default=DEFAULT_TOL_HZ / 1e6, metavar="MHZ",
                    help=f"Match tolerance in MHz for Pd_plat (default: {DEFAULT_TOL_HZ/1e6:.1f})")
parser.add_argument("--scan-steps", type=int, default=DEFAULT_STEPS, metavar="N",
                    help=f"Frequency steps per sweep (default: {DEFAULT_STEPS})")
args = parser.parse_args()

paths = find_results(run=args.run)
if args.classifier not in paths:
    raise SystemExit(f"[ERROR] no {args.classifier} run found")

results_csv = paths[args.classifier]
run_prefix  = os.path.basename(results_csv).replace("_results.csv", "")
logs_dir    = os.path.dirname(results_csv)

meta = load_meta(args.meta)
tol_hz = args.tolerance * 1e6


def _parse_events(path):
    confirmed_freqs = []
    n_rejected      = 0
    if not os.path.exists(path):
        return confirmed_freqs, n_rejected
    with open(path) as f:
        for line in f:
            m = CONF_RE.search(line)
            if m:
                confirmed_freqs.append(float(m.group(1)))
                continue
            if REJ_RE.search(line):
                n_rejected += 1
    return confirmed_freqs, n_rejected


per_sweep = []

with open(results_csv, newline="") as f:
    for row in csv.DictReader(f):
        iq = row["iq_folder"]
        events_log = os.path.join(logs_dir, f"{run_prefix}_{iq}", "events.log")
        confirmed_freqs, n_rej = _parse_events(events_log)

        m = meta.get(iq, {})
        drone_freq_str = m.get("drone_freq", "").strip().lower()
        is_pos = drone_freq_str not in ("", "none")

        hit_drone = False
        if is_pos:
            try:
                drone_hz = float(drone_freq_str) * 1e6
                hit_drone = any(abs(c - drone_hz) <= tol_hz for c in confirmed_freqs)
            except ValueError:
                pass

        per_sweep.append({
            "iq":          iq,
            "is_pos":      is_pos,
            "n_confirmed": len(confirmed_freqs),
            "n_rejected":  n_rej,
            "hit_drone":   hit_drone,
        })


def _agg(rows):
    n          = len(rows)
    n_conf     = sum(r["n_confirmed"] for r in rows)
    n_rej      = sum(r["n_rejected"]  for r in rows)
    n_hit      = sum(1 for r in rows if r["hit_drone"])
    mean_conf  = n_conf / n if n else float("nan")
    mean_rej   = n_rej  / n if n else float("nan")
    reduction  = 1 - (mean_conf / args.scan_steps) if n else float("nan")
    voting_rej = n_rej / (n_rej + n_conf) if (n_rej + n_conf) else float("nan")
    return {
        "n":          n,
        "n_conf":     n_conf,
        "n_rej":      n_rej,
        "n_hit":      n_hit,
        "mean_conf":  mean_conf,
        "mean_rej":   mean_rej,
        "reduction":  reduction,
        "voting_rej": voting_rej,
    }


positives = [r for r in per_sweep if r["is_pos"]]
negatives = [r for r in per_sweep if not r["is_pos"]]

a_pos = _agg(positives)
a_neg = _agg(negatives)
a_all = _agg(per_sweep)

pd_plat  = a_pos["n_hit"] / a_pos["n"] if a_pos["n"] else float("nan")
pfa_plat = a_neg["mean_conf"]


def _row(label, a, pd_str, pfa_str):
    print(f"{label:<22} {a['n']:>4d}   {a['mean_conf']:>8.2f}   {a['mean_rej']:>8.2f}   "
          f"{pd_str:>7}   {pfa_str:>9}   {fmt_pct(a['reduction']):>9}   {fmt_pct(a['voting_rej']):>7}")


print(f"{'category':<22} {'n':>4}   {'conf/sw':>8}   {'rej/sw':>8}   "
      f"{'Pd_plat':>7}   {'Pfa_plat':>9}   {'reduction':>9}   {'vote_rej':>7}")
print("-" * 95)
_row("positive (drone)",     a_pos, fmt_pct(pd_plat), "    -")
_row("negative (no drone)",  a_neg, "      -",        f"{pfa_plat:>9.2f}")
_row("overall",              a_all, "      -",        "    -")

print()
print(f"  Pd_plat   = sweeps where a confirmed plateau lands within ±{args.tolerance:.1f} MHz of drone_freq")
print(f"  Pfa_plat  = mean confirmed plateaus per drone-absent sweep")
print(f"  reduction = 1 − (mean confirmed / {args.scan_steps} scan steps per sweep)")
print(f"  vote_rej  = rejected / (rejected + confirmed)  [≥1 hit but < required]")
print()
print(f"  source: {results_csv}")
