import argparse
import os
from collections import defaultdict

def parse_events(path):
    events = []
    if not os.path.exists(path):
        print("No events.log exists")
        return events
    
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 3:
                continue

            ev = {"timestamp": parts[0], "type": parts[1], "message": parts[2]}
            for kv in parts[3:]:
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    ev[k] = v
            events.append(ev)
    return events


def parse_csv_log(path, columns):
    """Return list of dicts from a simple CSV log (no header)."""
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < len(columns):
                continue
            rows.append(dict(zip(columns, parts)))
    return rows

PLATEAU_COLS = ["timestamp", "center_freq", "bandwidth", "hit_count"]
VIDEO_COLS   = ["timestamp", "center_freq", "score", "sample_count"]

ERROR_TYPES = {"SDR_READ_ERROR", "ZERO_BUFFER", "QUEUE_FULL", "INVALID_BIN"}

def summarise_dir(log_dir):
    events   = parse_events(os.path.join(log_dir, "events.log"))
    plateaus = parse_csv_log(os.path.join(log_dir, "confirmed_plateau.log"), PLATEAU_COLS)
    videos   = parse_csv_log(os.path.join(log_dir, "video_detections.log"),  VIDEO_COLS)

    counts = defaultdict(int)
    for ev in events:
        counts[ev["type"]] += 1

    plateau_freqs = sorted(set(
        round(float(p["center_freq"]) / 1e6, 1) for p in plateaus
    ))

    video_freqs = []
    for v in videos:
        freq_mhz = float(v["center_freq"]) / 1e6
        score    = float(v["score"])
        video_freqs.append((freq_mhz, score))

    samples_dir = os.path.join(log_dir, "samples")
    saved_samples = 0
    if os.path.isdir(samples_dir):
        saved_samples = len([f for f in os.listdir(samples_dir) if f.endswith(".npy")])

    total_errors = sum(counts[t] for t in ERROR_TYPES)

    return {
        "plateaus_confirmed": len(plateaus),
        "plateaus_rejected":  counts.get("PLATEAU_REJECTED", 0),
        "plateau_freqs":      plateau_freqs,
        "video_confirmed":    len(videos),
        "video_rejected":     counts.get("VIDEO_REJECTED", 0),
        "video_detections":   video_freqs,
        "errors":             total_errors,
        "error_breakdown":    {t: counts[t] for t in ERROR_TYPES if counts[t] > 0},
        "saved_samples":      saved_samples,
    }

def print_single(label, s):
    total_plateau = s["plateaus_confirmed"] + s["plateaus_rejected"]
    reject_rate = (
        100 * s["plateaus_rejected"] / total_plateau if total_plateau else 0
    )

    print(f"\n{'=' * 50}")
    print(f"  {label}")
    print(f"{'=' * 50}")
    print(f"  Plateaus   confirmed : {s['plateaus_confirmed']}")
    print(f"             rejected  : {s['plateaus_rejected']}  ({reject_rate:.0f}% rejection rate)")
    if s["plateau_freqs"]:
        bands = _group_freqs(s["plateau_freqs"])
        print(f"             bands     : {bands}")
    print(f"  Video      confirmed : {s['video_confirmed']}")
    print(f"             rejected  : {s['video_rejected']}")
    if s["video_detections"]:
        for freq, score in sorted(s["video_detections"]):
            print(f"               {freq:>8.1f} MHz   score={score:.2f}")
    print(f"  Saved IQ samples     : {s['saved_samples']}")
    if s["errors"]:
        print(f"  Errors               : {s['errors']}  {s['error_breakdown']}")
    print()


def print_comparison(summaries):
    """summaries: dict of label -> summary dict"""
    labels = list(summaries.keys())

    print(f"\n{'=' * 70}")
    print(f"  CLASSIFIER COMPARISON")
    print(f"{'=' * 70}")

    col_w = 18
    header = f"{'Metric':<30}" + "".join(f"{l:>{col_w}}" for l in labels)
    print(header)
    print("-" * len(header))

    def row(name, fn):
        vals = "".join(f"{str(fn(summaries[l])):>{col_w}}" for l in labels)
        print(f"{name:<30}{vals}")

    row("Plateaus confirmed",  lambda s: s["plateaus_confirmed"])
    row("Plateaus rejected",   lambda s: s["plateaus_rejected"])
    row("Plateau reject rate", lambda s: _pct(s["plateaus_rejected"], s["plateaus_confirmed"] + s["plateaus_rejected"]))
    row("Video confirmed",     lambda s: s["video_confirmed"])
    row("Video rejected",      lambda s: s["video_rejected"])
    row("Saved IQ samples",    lambda s: s["saved_samples"])
    row("Errors",              lambda s: s["errors"])

    all_detections = {}
    for label, s in summaries.items():
        for freq, score in s["video_detections"]:
            all_detections.setdefault(freq, {})[label] = score

    if all_detections:
        print()
        print(f"  Confirmed detections by frequency:")
        freq_header = f"  {'Freq (MHz)':<15}" + "".join(f"{l:>{col_w}}" for l in labels)
        print(freq_header)
        print("  " + "-" * (len(freq_header) - 2))
        for freq in sorted(all_detections):
            vals = "".join(
                f"{all_detections[freq].get(l, '-'):>{col_w}}"
                for l in labels
            )
            print(f"  {freq:>8.1f} MHz      {vals}")

    print()

def _pct(num, denom):
    if denom == 0:
        return "n/a"
    return f"{100 * num / denom:.0f}%"

def _group_freqs(freqs, gap_mhz=50):
    if not freqs:
        return ""
    groups = []
    start = end = freqs[0]
    for f in freqs[1:]:
        if f - end <= gap_mhz:
            end = f
        else:
            groups.append(f"{start:.0f}–{end:.0f}" if start != end else f"{start:.0f}")
            start = end = f
    groups.append(f"{start:.0f}–{end:.0f}" if start != end else f"{start:.0f}")
    return ", ".join(groups) + " MHz"

def main():
    parser = argparse.ArgumentParser(description="Summarise a detection run or compare classifier runs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run-name", metavar="NAME",
                       help="Run name prefix (finds <name>_harmonic, _cyclo, _autocorr dirs)")
    group.add_argument("--log-dir", metavar="DIR",
                       help="Single log directory to summarise")
    parser.add_argument("--logs-base", metavar="DIR", default="logs",
                        help="Base logs directory (default: logs)")
    args = parser.parse_args()

    if args.log_dir:
        s = summarise_dir(args.log_dir)
        print_single(os.path.basename(args.log_dir), s)
        return

    classifiers = ["harmonic", "cyclo", "autocorr"]
    summaries = {}
    for clf in classifiers:
        d = os.path.join(args.logs_base, f"{args.run_name}_{clf}")
        if os.path.isdir(d):
            summaries[clf] = summarise_dir(d)
        else:
            print(f"  [warn] directory not found: {d}")

    if len(summaries) == 1:
        label, s = next(iter(summaries.items()))
        print_single(label, s)
    elif summaries:
        print_comparison(summaries)
    else:
        print("No run directories found.")

if __name__ == "__main__":
    main()
