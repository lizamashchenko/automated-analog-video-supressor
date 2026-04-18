import argparse
import csv
import os
import sys


def parse_detections(log_path):
    """Return list of (freq_mhz, score) from video_detections.log."""
    out = []
    if not os.path.exists(log_path):
        return out
    with open(log_path) as f:
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 3:
                continue
            try:
                freq_mhz = float(parts[1]) / 1e6
                score    = float(parts[2])
            except ValueError:
                continue
            out.append((freq_mhz, score))
    return out


def classify(truth_mhz, detections, tolerance_mhz):
    """Classify one sweep against ground truth.

    Returns dict with tp (bool), fn (bool), fp_count (int), matched, spurious.
    """
    matched  = []
    spurious = []

    for freq, score in detections:
        if truth_mhz is not None and abs(freq - truth_mhz) <= tolerance_mhz:
            matched.append((freq, score))
        else:
            spurious.append((freq, score))

    if truth_mhz is None:
        tp = False
        fn = False
    else:
        tp = len(matched) > 0
        fn = len(matched) == 0

    return {
        "tp":       tp,
        "fn":       fn,
        "fp_count": len(spurious),
        "matched":  matched,
        "spurious": spurious,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Build a per-sweep TP/FP/FN CSV from a dataset run"
    )
    parser.add_argument("run_prefix",
                        help="Run prefix passed to run_dataset.sh (e.g. dataset_harmonic_20260416_120000)")
    parser.add_argument("--metadata", default="/home/liza/UCU/diploma/dataset/iq_recording_meta.csv")
    parser.add_argument("--logs-base", default="logs")
    parser.add_argument("--output",    default=None,
                        help="Output CSV path (default: logs/<prefix>_results.csv)")
    parser.add_argument("--tolerance-mhz", type=float, default=20.0,
                        help="Frequency tolerance for matching detection to truth (default: 20 MHz)")
    args = parser.parse_args()

    if not os.path.exists(args.metadata):
        print(f"metadata csv not found: {args.metadata}", file=sys.stderr)
        sys.exit(1)

    output = args.output or os.path.join(args.logs_base, f"{args.run_prefix}_results.csv")

    rows = []
    totals = {"tp": 0, "fn": 0, "fp_count": 0, "tn": 0, "positives": 0, "negatives": 0}

    with open(args.metadata, newline="") as f:
        reader = csv.DictReader(f)
        for meta in reader:
            folder = meta["iq_folder"].strip()
            if not folder:
                continue

            drone_freq = meta["drone_freq"].strip()
            if drone_freq.lower() == "none" or drone_freq == "":
                truth_mhz = None
                totals["negatives"] += 1
            else:
                try:
                    truth_mhz = float(drone_freq)
                    totals["positives"] += 1
                except ValueError:
                    print(f"  [warn] unparseable drone_freq='{drone_freq}' in {folder}, skipping")
                    continue

            log_dir = os.path.join(args.logs_base, f"{args.run_prefix}_{folder}")
            detections = parse_detections(os.path.join(log_dir, "video_detections.log"))
            result = classify(truth_mhz, detections, args.tolerance_mhz)

            if truth_mhz is None and result["fp_count"] == 0:
                totals["tn"] += 1
            totals["tp"]       += int(result["tp"])
            totals["fn"]       += int(result["fn"])
            totals["fp_count"] += result["fp_count"]

            rows.append({
                "id":               meta.get("id", ""),
                "iq_folder":        folder,
                "environment":      meta.get("environment", ""),
                "obstacles":        meta.get("obtacles", ""),
                "distance_m":       meta.get("distance _m", ""),
                "drone_freq_mhz":   "none" if truth_mhz is None else f"{truth_mhz:g}",
                "detections_mhz":   " ".join(f"{f:.1f}" for f, _ in detections),
                "matched_mhz":      " ".join(f"{f:.1f}" for f, _ in result["matched"]),
                "spurious_mhz":     " ".join(f"{f:.1f}" for f, _ in result["spurious"]),
                "tp":               int(result["tp"]),
                "fn":               int(result["fn"]),
                "fp_count":         result["fp_count"],
                "log_dir_exists":   int(os.path.isdir(log_dir)),
            })

    if not rows:
        print("No rows collected — check metadata CSV and run prefix.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    tp = totals["tp"]
    fn = totals["fn"]
    fp = totals["fp_count"]
    tn = totals["tn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0

    print()
    print("================================================")
    print(f"  Dataset results: {args.run_prefix}")
    print("================================================")
    print(f"  sweeps with drone : {totals['positives']}")
    print(f"  sweeps without    : {totals['negatives']}")
    print(f"  TP : {tp}")
    print(f"  FN : {fn}")
    print(f"  TN : {tn}  (clean sweeps, zero detections)")
    print(f"  FP : {fp}  (total spurious detections across all sweeps)")
    print(f"  precision : {precision:.2f}")
    print(f"  recall    : {recall:.2f}")
    print(f"  CSV       : {output}")
    print("================================================")


if __name__ == "__main__":
    main()
