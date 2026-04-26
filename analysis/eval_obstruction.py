import argparse

from analysis.eval_common import (
    CLASSIFIERS, find_results, load_rows, load_meta, is_positive, fmt_pct,
)
from utils.config import load as load_config

# Pd / Pfa by obstruction category, combined over all three classifiers
# usage: eval_obstruction.py [-h] [--run TS] [--meta PATH]

DEFAULT_META = load_config()["dataset"]["metadata_csv"]

OBS_CATEGORIES = [
    ("line of sight",        lambda obs, fd: obs == "none"),
    ("panel wall",           lambda obs, fd: obs == "panel_wall"),
    ("brick walls",          lambda obs, fd: obs == "brick_walls" and fd == 0),
    ("brick walls + floor",  lambda obs, fd: obs == "brick_walls" and fd == 1),
    ("movement",             lambda obs, fd: obs == "movement"),
]

parser = argparse.ArgumentParser(description="Pd/Pfa by obstruction, combined across classifiers")
parser.add_argument("--run", metavar="TS", help="Run timestamp (default: latest)")
parser.add_argument("--meta", metavar="PATH", default=DEFAULT_META,
                    help=f"Metadata CSV (default: {DEFAULT_META})")
args = parser.parse_args()

paths = find_results(run=args.run)
if not paths:
    raise SystemExit("[ERROR] no results CSVs found")

meta = load_meta(args.meta)


buckets = {label: {
    "trials": 0, "tp": 0, "fn": 0,
    "fp_total": 0, "fp_trials": 0,
    "distances": set(), "powers": set(), "freqs": set(),
} for label, _ in OBS_CATEGORIES}


def _match(obstacles, floor_diff):
    for label, pred in OBS_CATEGORIES:
        if pred(obstacles, floor_diff):
            return label
    return None


for cls in CLASSIFIERS:
    if cls not in paths:
        continue
    for r in load_rows(paths[cls]):
        if not is_positive(r):
            continue

        m = meta.get(r["iq_folder"], {})
        label = _match(r["obstacles"], m.get("floor_diff", 0))
        if label is None:
            continue

        b = buckets[label]
        b["trials"]   += 1
        b["tp"]       += r["tp"]
        b["fn"]       += r["fn"]
        b["fp_total"] += r["fp_count"]
        if r["fp_count"] > 0:
            b["fp_trials"] += 1
        if m.get("distance_m"):
            b["distances"].add(m["distance_m"])
        if m.get("vtx_power_mw") is not None:
            b["powers"].add(int(m["vtx_power_mw"]))
        b["freqs"].add(r["drone_freq_mhz"])


def _fmt_set(s, suffix=""):
    if not s:
        return "-"
    items = sorted(s, key=lambda x: (float(x.split("-")[0]) if x[0].isdigit() else float("inf")))
    return ",".join(f"{x}{suffix}" for x in items)


print(f"{'obstruction':<20} {'trials':>7} {'freq':>18} {'power':>8} {'dist':>10}  "
      f"{'TP':>4} {'FN':>4} {'FP':>4}   {'Pd':>6}   {'Pfa':>6}   {'FP/trial':>8}")
print("-" * 114)

for label, _ in OBS_CATEGORIES:
    b = buckets[label]
    if b["trials"] == 0:
        continue

    pd  = b["tp"] / (b["tp"] + b["fn"]) if (b["tp"] + b["fn"]) else float("nan")
    pfa = b["fp_trials"] / b["trials"]
    fpr = b["fp_total"]  / b["trials"]

    freqs = _fmt_set(b["freqs"], "MHz")
    pow_s = ",".join(f"{p}mW" for p in sorted(b["powers"])) or "-"
    dist  = _fmt_set(b["distances"], "m")

    print(f"{label:<20} {b['trials']:>7d} {freqs:>18} {pow_s:>8} {dist:>10}  "
          f"{b['tp']:>4d} {b['fn']:>4d} {b['fp_total']:>4d}   "
          f"{fmt_pct(pd):>6}   {fmt_pct(pfa):>6}   {fpr:>8.2f}")

print()
print("  trials = positive sweeps × 3 classifiers")
print("  Pd  = TP / (TP + FN)")
print("  Pfa = fraction of trials with ≥1 spurious detection")
print("  FP/trial = mean spurious detections per (sweep × classifier)")
print("  power/distance shown for context — groups are not equal-condition")
