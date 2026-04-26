import argparse

from analysis.eval_common import (
    CLASSIFIERS, find_results, load_rows, load_meta, is_positive, fmt_pct,
)
from utils.config import load as load_config


# usage: eval_distance.py [-h] [--run TS] [--meta PATH]

# Pd / Pfa vs distance, combined over all three classifiers (each
# sweep × classifier counted as one trial). Filters: vtx_power_mw = 25
# AND obstacles = none.


DEFAULT_META = load_config()["dataset"]["metadata_csv"]

parser = argparse.ArgumentParser(description="Pd/Pfa vs distance, combined across classifiers (25 mW, no obstacles)")
parser.add_argument("--run", metavar="TS", help="Run timestamp (default: latest)")
parser.add_argument("--meta", metavar="PATH", default=DEFAULT_META,
                    help=f"Metadata CSV with vtx_power_mw (default: {DEFAULT_META})")
args = parser.parse_args()

paths = find_results(run=args.run)
if not paths:
    raise SystemExit("[ERROR] no results CSVs found")

meta = load_meta(args.meta)


def _is_included(row):
    m = meta.get(row["iq_folder"])
    if m is None:
        return False
    if m["vtx_power_mw"] != 25:
        return False
    if m["obstacles"] != "none":
        return False
    return is_positive(row)


def _sort_key(d):
    try:
        return float(d)
    except ValueError:
        return float("inf")


buckets = {}
for cls in CLASSIFIERS:
    if cls not in paths:
        continue
    for r in load_rows(paths[cls]):
        if not _is_included(r):
            continue
        d = r["distance_m"]
        b = buckets.setdefault(d, {
            "trials": 0, "tp": 0, "fn": 0,
            "fp_total": 0, "fp_trials": 0,
            "freqs": set(),
        })
        b["trials"]   += 1
        b["tp"]       += r["tp"]
        b["fn"]       += r["fn"]
        b["fp_total"] += r["fp_count"]
        if r["fp_count"] > 0:
            b["fp_trials"] += 1
        b["freqs"].add(r["drone_freq_mhz"])


print(f"{'distance':>10} {'trials':>7} {'transmitters':>22} "
      f"{'TP':>4} {'FN':>4} {'FP':>4}   {'Pd':>6}   {'Pfa':>6}   {'FP/trial':>8}")
print("-" * 86)

for d in sorted(buckets, key=_sort_key):
    b = buckets[d]
    trials = b["trials"]
    pd  = b["tp"] / (b["tp"] + b["fn"]) if (b["tp"] + b["fn"]) else float("nan")
    pfa = b["fp_trials"] / trials if trials else float("nan")
    fpr = b["fp_total"]  / trials if trials else float("nan")
    freqs = ",".join(sorted(b["freqs"], key=_sort_key)) + "MHz"

    print(f"{d + ' m':>10} {trials:>7d} {freqs:>22} "
          f"{b['tp']:>4d} {b['fn']:>4d} {b['fp_total']:>4d}   "
          f"{fmt_pct(pd):>6}   {fmt_pct(pfa):>6}   {fpr:>8.2f}")

print()
print("  trials = positive sweeps × 3 classifiers")
print("  Pd  = TP / (TP + FN)")
print("  Pfa = fraction of trials with ≥1 spurious detection")
print("  FP/trial = mean spurious detections per (sweep × classifier)")
