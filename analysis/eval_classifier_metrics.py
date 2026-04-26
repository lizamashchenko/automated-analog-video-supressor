import argparse

from analysis.eval_common import (
    CLASSIFIERS, find_results, load_rows, aggregate, fmt_pct,
)


# usage: eval_classifier_metrics.py [-h] [--run TS] [--logs-dir DIR]

# Aggregate TP/FP/FN plus precision/recall/F1 per classifier across the
# whole dataset. Uses the latest run per classifier unless --run is given.


parser = argparse.ArgumentParser(description="Per-classifier precision/recall/F1 over the full dataset")
parser.add_argument("--run", metavar="TS",
                    help="Timestamp of the run to use (e.g. 20260424_201338). Default: latest per classifier.")
parser.add_argument("--logs-dir", metavar="DIR", default=None,
                    help="Logs directory (default: project logs/)")
args = parser.parse_args()

paths = find_results(logs_dir=args.logs_dir or None, run=args.run) \
        if args.logs_dir else find_results(run=args.run)

if not paths:
    raise SystemExit("[ERROR] no results CSVs found")

print(f"{'classifier':<11} {'n':>4} {'pos':>4} {'neg':>4} "
      f"{'TP':>4} {'FN':>4} {'FP':>4} "
      f"{'precision':>10} {'recall':>9} {'F1':>7}")
print("-" * 73)

for cls in CLASSIFIERS:
    if cls not in paths:
        print(f"{cls:<11}  (no results found)")
        continue

    rows = load_rows(paths[cls])
    a = aggregate(rows)

    print(f"{cls:<11} {a['n']:>4d} {a['n_pos']:>4d} {a['n_neg']:>4d} "
          f"{a['tp']:>4d} {a['fn']:>4d} {a['fp']:>4d} "
          f"{fmt_pct(a['precision']):>10} {fmt_pct(a['recall']):>9} "
          f"{fmt_pct(a['f1'], 2):>7}")

print()
print("  n_pos = sweeps with a drone present; n_neg = drone=none sweeps")
print("  precision = TP / (TP+FP) | recall = TP / (TP+FN)")
print()
print("sources:")
for cls, p in paths.items():
    print(f"  {cls:<10} {p}")
