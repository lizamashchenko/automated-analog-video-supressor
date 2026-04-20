#!/usr/bin/env python3
"""Grid-search classifier parameters on an existing dataset run.

Usage:
    python3 analysis/tune_classifier.py <run_prefix> <classifier>
        [--metadata PATH] [--logs-base DIR] [--exclude-freqs 762,1100-1300]
        [--top N]

Examples:
    python3 analysis/tune_classifier.py dataset_cyclo_20260419_132451 cyclo
    python3 analysis/tune_classifier.py dataset_autocorr_20260418 autocorr --exclude-freqs 762
    python3 analysis/tune_classifier.py dataset_harmonic_20260420 harmonic --top 5

Reads the _results.csv and per-sweep debug logs to simulate every
parameter combination, then prints a ranked table of configs.
"""

import argparse
import csv
import glob
import os
import re
import sys
from dataclasses import dataclass, field


# ── Log parsers ──────────────────────────────────────────────────────────

def parse_cyclo_logs(log_dir):
    """Return list of (freq_hz, [sample_dicts]) from cyclo_debug.log."""
    path = os.path.join(log_dir, "cyclo_debug.log")
    if not os.path.exists(path):
        return []

    with open(path) as f:
        lines = f.readlines()

    groups = []
    cur_freq = None
    cur_samples = []

    for line in lines:
        if "CYCLO_SAMPLE" in line:
            m_freq = re.search(r"freq=([\d.]+)", line)
            m_ratios = re.search(r"ratios=\[([\d., ]+)\]", line)
            m_spread = re.search(r"max_spread_db=([\d.]+)", line)
            if not (m_freq and m_ratios and m_spread):
                continue
            freq = float(m_freq.group(1))
            ratios = [float(x) for x in m_ratios.group(1).split(", ")]
            spread = float(m_spread.group(1))
            if cur_freq is None or abs(freq - cur_freq) > 1e6:
                if cur_freq is not None and cur_samples:
                    groups.append((cur_freq, cur_samples))
                cur_freq = freq
                cur_samples = []
            cur_samples.append({"ratios": ratios, "spread": spread})
        elif "CYCLO_RESULT" in line:
            if cur_freq is not None and cur_samples:
                groups.append((cur_freq, cur_samples))
            cur_freq = None
            cur_samples = []

    if cur_freq is not None and cur_samples:
        groups.append((cur_freq, cur_samples))
    return groups


def parse_autocorr_logs(log_dir):
    """Return list of (freq_hz, [sample_dicts]) from autocorr_debug.log."""
    path = os.path.join(log_dir, "autocorr_debug.log")
    if not os.path.exists(path):
        return []

    with open(path) as f:
        lines = f.readlines()

    groups = []
    cur_freq = None
    cur_samples = []

    for line in lines:
        if "AUTOCORR_SAMPLE" in line:
            m_freq = re.search(r"freq=([\d.]+)", line)
            m_peak = re.search(r"peak=([\d.e+-]+)", line)
            m_peak2 = re.search(r"peak2=([\d.e+-]+)", line)
            m_lag = re.search(r"lag_off=([\d.e+-]+)", line)
            if not (m_freq and m_peak and m_peak2 and m_lag):
                continue
            freq = float(m_freq.group(1))
            peak = float(m_peak.group(1))
            peak2 = float(m_peak2.group(1))
            lag_off = float(m_lag.group(1))
            if cur_freq is None or abs(freq - cur_freq) > 1e6:
                if cur_freq is not None and cur_samples:
                    groups.append((cur_freq, cur_samples))
                cur_freq = freq
                cur_samples = []
            cur_samples.append({"peak": peak, "peak2": peak2, "lag_off": lag_off})
        elif "AUTOCORR_RESULT" in line:
            if cur_freq is not None and cur_samples:
                groups.append((cur_freq, cur_samples))
            cur_freq = None
            cur_samples = []

    if cur_freq is not None and cur_samples:
        groups.append((cur_freq, cur_samples))
    return groups


def _parse_harmonic_dict(s):
    """Parse the harmonics={...} field from harmonic debug log.

    Format: {1: {'above_noise': 5.2, 'peak_to_valley': 3.1}, 2: None, ...}
    Returns dict: {harmonic_idx: {'above_noise': float, 'peak_to_valley': float} | None}
    """
    result = {}
    # Match each harmonic entry: N: {'above_noise': X, 'peak_to_valley': Y} or N: None
    for m in re.finditer(
        r"(\d+):\s*(?:None|\{'above_noise':\s*([-\d.]+),\s*'peak_to_valley':\s*([-\d.]+)\})",
        s
    ):
        h = int(m.group(1))
        if m.group(2) is None:
            result[h] = None
        else:
            result[h] = {
                "above_noise": float(m.group(2)),
                "peak_to_valley": float(m.group(3)),
            }
    return result


def parse_harmonic_logs(log_dir):
    """Return list of (freq_hz, [sample_dicts]) from harmonic_debug.log."""
    path = os.path.join(log_dir, "harmonic_debug.log")
    if not os.path.exists(path):
        return []

    with open(path) as f:
        lines = f.readlines()

    groups = []
    cur_freq = None
    cur_samples = []

    for line in lines:
        if "HARMONIC_SAMPLE" in line:
            m_freq = re.search(r"freq=([\d.]+)", line)
            m_spread = re.search(r"max_spread=([\d.]+)", line)
            m_harmonics = re.search(r"harmonics=(\{.+\})\s*$", line)
            if not (m_freq and m_spread):
                continue
            freq = float(m_freq.group(1))
            spread = float(m_spread.group(1))
            harmonics = _parse_harmonic_dict(m_harmonics.group(1)) if m_harmonics else {}
            if cur_freq is None or abs(freq - cur_freq) > 1e6:
                if cur_freq is not None and cur_samples:
                    groups.append((cur_freq, cur_samples))
                cur_freq = freq
                cur_samples = []
            cur_samples.append({"spread": spread, "harmonics": harmonics})
        elif "HARMONIC_RESULT" in line:
            if cur_freq is not None and cur_samples:
                groups.append((cur_freq, cur_samples))
            cur_freq = None
            cur_samples = []

    if cur_freq is not None and cur_samples:
        groups.append((cur_freq, cur_samples))
    return groups


LOG_PARSERS = {
    "cyclo": parse_cyclo_logs,
    "autocorr": parse_autocorr_logs,
    "harmonic": parse_harmonic_logs,
}


# ── Vote simulators ─────────────────────────────────────────────────────

def sim_cyclo(samples, params):
    """Count votes for cyclo classifier with given params."""
    rt = params["ratio_threshold"]
    min_h = params["min_harmonics"]
    max_sp = params["max_harmonic_spread_db"]
    votes = 0
    for s in samples:
        h_above = sum(1 for r in s["ratios"] if r > rt)
        if h_above >= min_h and s["spread"] <= max_sp:
            votes += 1
    return votes


def sim_autocorr(samples, params):
    """Count votes for autocorr classifier with given params."""
    pt = params["peak_threshold"]
    st = params["secondary_threshold"]
    ls = params["lag_strict"]
    votes = 0
    for s in samples:
        if (s["peak"] > pt
                and s["peak2"] > st
                and abs(s["lag_off"]) <= ls):
            votes += 1
    return votes


def sim_harmonic(samples, params):
    """Simulate harmonic classifier — returns confirmed_harmonics count.

    The harmonic classifier doesn't use per-buffer voting. Instead it counts,
    for each harmonic, the fraction of buffers where that harmonic was a hit.
    A harmonic is "confirmed" if its hit ratio >= harmonic_ratio.
    Detection occurs when confirmed_harmonics >= required_harmonics.

    We return the count of confirmed harmonics so the caller can compare
    against required_harmonics (mapped to required_votes in the grid).
    """
    threshold_db = params["threshold_db"]
    valley_drop_db = params["valley_drop_db"]
    max_sp = params["max_harmonic_spread_db"]
    harmonic_ratio = params["harmonic_ratio"]

    total = len(samples)
    if total == 0:
        return 0

    # Collect all harmonic indices across samples
    all_harmonics = set()
    for s in samples:
        all_harmonics.update(s["harmonics"].keys())

    hit_counts = {h: 0 for h in all_harmonics}

    for s in samples:
        if s["spread"] > max_sp:
            continue
        for h, data in s["harmonics"].items():
            if data is None:
                continue
            if (data["above_noise"] > threshold_db
                    and data["peak_to_valley"] > valley_drop_db):
                hit_counts[h] += 1

    confirmed = sum(
        1 for count in hit_counts.values()
        if count / total >= harmonic_ratio
    )
    return confirmed


VOTE_SIMULATORS = {
    "cyclo": sim_cyclo,
    "autocorr": sim_autocorr,
    "harmonic": sim_harmonic,
}


# ── Parameter grids ──────────────────────────────────────────────────────

PARAM_GRIDS = {
    "cyclo": {
        "ratio_threshold":        [2.0, 2.3, 2.5, 2.8, 3.0, 3.2, 3.5, 3.9],
        "min_harmonics":          [2, 3],
        "max_harmonic_spread_db": [6, 8, 9, 10, 12, 15],
        "required_votes":         [2, 3, 4, 5],
    },
    "autocorr": {
        "peak_threshold":      [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50],
        "secondary_threshold": [0.08, 0.10, 0.12, 0.14, 0.17, 0.20],
        "lag_strict":          [1, 2, 3],
        "required_votes":      [2, 3, 4, 5],
    },
    "harmonic": {
        "threshold_db":           [4, 5, 6, 8, 10],
        "valley_drop_db":         [2, 3, 4, 5, 6],
        "max_harmonic_spread_db": [6, 8, 10, 12, 15],
        "harmonic_ratio":         [0.3, 0.4, 0.5, 0.6],
        "required_votes":         [2, 3, 4],
    },
}


# ── Exclusion filter ─────────────────────────────────────────────────────

def parse_exclude_spec(spec):
    """Parse comma-separated freq specs like '762,1100-1300,2450'.

    Returns list of (lo_mhz, hi_mhz) ranges.
    """
    if not spec:
        return []
    ranges = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            ranges.append((float(lo), float(hi)))
        else:
            val = float(part)
            ranges.append((val - 5, val + 5))
    return ranges


def is_excluded(freq_hz, exclude_ranges):
    freq_mhz = freq_hz / 1e6
    return any(lo <= freq_mhz <= hi for lo, hi in exclude_ranges)


def load_metadata(path):
    """Load metadata CSV into {iq_folder: {col: val}} dict."""
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return {row["iq_folder"].strip(): row for row in reader if row.get("iq_folder", "").strip()}


def parse_sweep_exclusions(spec, metadata):
    """Parse --exclude-sweeps spec and return set of excluded folder names.

    Spec format: 'key=val[,key=val]' — all conditions must match (AND).
    Multiple groups separated by ';' are ORed.

    Examples:
        'drone_freq=1240,distance _m=1.5'       — 1240 MHz at 1.5 m
        'drone_freq=1240,distance _m=1.5;drone_freq=5840,distance _m=0'
    """
    if not spec:
        return set()

    excluded = set()
    for group in spec.split(";"):
        conditions = []
        for part in group.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            conditions.append((key.strip(), val.strip()))

        if not conditions:
            continue

        for folder, meta in metadata.items():
            if all(meta.get(k, "").strip() == v for k, v in conditions):
                excluded.add(folder)

    return excluded


# ── Grid-search engine ───────────────────────────────────────────────────

@dataclass
class Config:
    params: dict
    tp: int = 0
    fn: int = 0
    fp: int = 0
    fp_freqs: list = field(default_factory=list)
    fn_freqs: list = field(default_factory=list)


def grid_search(classifier, all_data, folder_info, exclude_ranges,
                excluded_sweeps=None):
    grid = PARAM_GRIDS[classifier]
    sim_fn = VOTE_SIMULATORS[classifier]

    # Count total matched detections (ground truth positives)
    excluded_sweeps = excluded_sweeps or set()
    total_matched = 0
    for folder, freq_hz, samples in all_data:
        if folder not in folder_info:
            continue
        matched, _ = folder_info[folder]
        if any(abs(freq_hz - m) < 3e6 for m in matched):
            total_matched += 1

    # Build list of all param combos
    param_names = [k for k in grid if k != "required_votes"]
    rv_values = grid["required_votes"]

    def _combos(names, grid):
        if not names:
            yield {}
            return
        name = names[0]
        for val in grid[name]:
            for rest in _combos(names[1:], grid):
                rest[name] = val
                yield rest

    configs = []
    for base in _combos(param_names, grid):
        for rv in rv_values:
            p = dict(base)
            p["required_votes"] = rv
            configs.append(Config(params=p))

    # Evaluate each config
    for cfg in configs:
        for folder, freq_hz, samples in all_data:
            if folder not in folder_info:
                continue
            matched, spurious = folder_info[folder]
            freq_mhz = freq_hz / 1e6

            is_matched = any(abs(freq_hz - m) < 3e6 for m in matched)
            is_spurious = any(abs(freq_hz - s) < 3e6 for s in spurious)

            if is_spurious and (
                is_excluded(freq_hz, exclude_ranges)
                or (excluded_sweeps and folder in excluded_sweeps)
            ):
                continue

            votes = sim_fn(samples, cfg.params)
            confirmed = votes >= cfg.params["required_votes"]

            if is_matched:
                if confirmed:
                    cfg.tp += 1
                else:
                    cfg.fn += 1
                    cfg.fn_freqs.append(f"{folder[-6:]}@{freq_mhz:.0f}")
            elif is_spurious:
                if confirmed:
                    cfg.fp += 1
                    cfg.fp_freqs.append(f"{freq_mhz:.0f}")

    return configs, total_matched


# ── Scoring & ranking ────────────────────────────────────────────────────

def score_config(cfg, total_positives):
    """Score a config. Higher is better. Heavily penalises FN, then FP."""
    recall = cfg.tp / total_positives if total_positives else 0
    precision = cfg.tp / (cfg.tp + cfg.fp) if (cfg.tp + cfg.fp) else 0
    # F1-like but weight recall 2x
    if precision + recall == 0:
        return 0.0
    f_beta = (1 + 4) * precision * recall / (4 * precision + recall)
    return f_beta


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_prefix", help="Run prefix (e.g. dataset_cyclo_20260419_132451)")
    parser.add_argument("classifier", choices=["cyclo", "autocorr", "harmonic"])
    parser.add_argument("--metadata", default="/home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv")
    parser.add_argument("--logs-base", default="logs")
    parser.add_argument("--exclude-freqs", default=None,
                        help="Comma-separated MHz freqs/ranges to exclude from FP count "
                             "(e.g. '762,1100-1300,2400-2500,3200-3300')")
    parser.add_argument("--exclude-sweeps", default=None,
                        help="Exclude all FPs from sweeps matching metadata conditions. "
                             "Format: 'key=val,key=val' (AND); groups separated by ';' (OR). "
                             "E.g. 'drone_freq=1240,distance _m=1.5'")
    parser.add_argument("--top", type=int, default=15, help="Show top N configs (default 15)")
    parser.add_argument("--tolerance-mhz", type=float, default=20.0)
    args = parser.parse_args()

    # ── Load results CSV ──
    results_csv = os.path.join(args.logs_base, f"{args.run_prefix}_results.csv")
    if not os.path.exists(results_csv):
        print(f"Results CSV not found: {results_csv}", file=sys.stderr)
        sys.exit(1)

    with open(results_csv) as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    folder_info = {}
    total_positive_sweeps = 0
    for row in rows:
        folder = row["iq_folder"]
        matched = [float(m) * 1e6 for m in row["matched_mhz"].split()] if row["matched_mhz"].strip() else []
        spurious = [float(m) * 1e6 for m in row["spurious_mhz"].split()] if row["spurious_mhz"].strip() else []
        folder_info[folder] = (matched, spurious)
        if row["drone_freq_mhz"].strip() != "none":
            total_positive_sweeps += 1

    # ── Parse debug logs ──
    log_parser = LOG_PARSERS[args.classifier]
    log_dirs = sorted(glob.glob(os.path.join(args.logs_base, f"{args.run_prefix}_sweep_*")))

    all_data = []
    for log_dir in log_dirs:
        folder = os.path.basename(log_dir).split(f"{args.run_prefix}_")[-1]
        groups = log_parser(log_dir)
        for freq_hz, samples in groups:
            # Only include freqs that appeared in detections (had a plateau)
            if folder in folder_info:
                matched, spurious = folder_info[folder]
                is_relevant = (
                    any(abs(freq_hz - m) < 3e6 for m in matched)
                    or any(abs(freq_hz - s) < 3e6 for s in spurious)
                )
                if is_relevant:
                    all_data.append((folder, freq_hz, samples))

    if not all_data:
        print("No classifier debug logs found. Make sure verbosity >= 3 was used.", file=sys.stderr)
        sys.exit(1)

    exclude_ranges = parse_exclude_spec(args.exclude_freqs)
    metadata = load_metadata(args.metadata) if args.exclude_sweeps else {}
    excluded_sweeps = parse_sweep_exclusions(args.exclude_sweeps, metadata)

    print(f"Run:        {args.run_prefix}")
    print(f"Classifier: {args.classifier}")
    print(f"Sweeps:     {len(rows)} ({total_positive_sweeps} with drone)")
    print(f"Detections: {len(all_data)} plateau+classifier events in logs")
    if exclude_ranges:
        print(f"Excluding:  {args.exclude_freqs} MHz from FP count")
    if excluded_sweeps:
        print(f"Excluding sweeps: {len(excluded_sweeps)} matched ({args.exclude_sweeps})")
    print()

    # ── Grid search ──
    configs, total_matched = grid_search(
        args.classifier, all_data, folder_info, exclude_ranges, excluded_sweeps
    )

    # ── Rank ──
    for cfg in configs:
        cfg._score = score_config(cfg, total_matched)
    configs.sort(key=lambda c: (-c._score, c.fp, c.fn))

    # ── Print top N ──
    param_names = [k for k in PARAM_GRIDS[args.classifier]]
    header_parts = [f"{p:>10s}" for p in param_names]
    header = " ".join(header_parts) + "  | TP  FN  FP  score | FP freqs                 | FN freqs"
    print(header)
    print("-" * len(header))

    seen = set()
    printed = 0
    for cfg in configs:
        key = tuple(sorted(cfg.params.items()))
        if key in seen:
            continue
        seen.add(key)

        vals = " ".join(f"{cfg.params[p]:>10g}" for p in param_names)
        fp_str = " ".join(cfg.fp_freqs[:6])
        fn_str = " ".join(cfg.fn_freqs[:4])
        print(f"{vals}  | {cfg.tp:2d}  {cfg.fn:2d}  {cfg.fp:2d}  {cfg._score:.3f} | {fp_str:<25s}| {fn_str}")

        printed += 1
        if printed >= args.top:
            break

    # ── Suggest best ──
    # Map grid param names to config.toml names where they differ
    toml_names = {
        "harmonic": {"required_votes": "required_harmonics"},
    }
    name_map = toml_names.get(args.classifier, {})

    best = configs[0]
    print()
    print("=" * 60)
    print(f"  Suggested [classifier.{args.classifier}] config:")
    print("=" * 60)
    for p in param_names:
        toml_key = name_map.get(p, p)
        print(f"  {toml_key:30s} = {best.params[p]}")
    print(f"  -> TP={best.tp}  FN={best.fn}  FP={best.fp}")
    if best.fp_freqs:
        print(f"  -> FP at: {' '.join(best.fp_freqs)}")
    if best.fn_freqs:
        print(f"  -> FN at: {' '.join(best.fn_freqs)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
