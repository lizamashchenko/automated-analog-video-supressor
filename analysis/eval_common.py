import csv
import glob
import os
import re


LOGS_DIR     = "/home/liza/UCU/diploma/analog-video-supressor/logs"
CLASSIFIERS  = ("harmonic", "cyclo", "autocorr")
RESULT_RE    = re.compile(r"^dataset_(?P<cls>\w+?)_(?P<ts>\d{8}_\d{6})_results\.csv$")


def find_results(logs_dir=LOGS_DIR, run=None, classifiers=CLASSIFIERS):
    matches = {c: [] for c in classifiers}

    for name in os.listdir(logs_dir):
        m = RESULT_RE.match(name)
        if not m:
            continue
        cls = m["cls"]
        if cls not in matches:
            continue
        matches[cls].append((m["ts"], os.path.join(logs_dir, name)))

    out = {}
    for cls, items in matches.items():
        if not items:
            continue
        if run:
            sel = [p for ts, p in items if ts == run]
            if sel:
                out[cls] = sel[0]
        else:
            out[cls] = sorted(items)[-1][1]

    return out


def _parse_float(s, default=None):
    if s is None or s == "" or s == "none":
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _parse_int(s, default=0):
    if s is None or s == "":
        return default
    try:
        return int(s)
    except ValueError:
        return default


def load_rows(path):
    rows = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            rows.append({
                "id":              _parse_int(row.get("id")),
                "iq_folder":       row.get("iq_folder", ""),
                "environment":     row.get("environment", ""),
                "obstacles":       row.get("obstacles", ""),
                "distance_m":      row.get("distance_m", ""),
                "drone_freq_mhz":  row.get("drone_freq_mhz", ""),
                "tp":              _parse_int(row.get("tp")),
                "fn":              _parse_int(row.get("fn")),
                "fp_count":        _parse_int(row.get("fp_count")),
            })
    return rows


def load_meta(meta_path):
    out = {}
    with open(meta_path, newline="") as f:
        for row in csv.DictReader(f):
            out[row["iq_folder"]] = {
                "drone_freq":    row.get("drone_freq", ""),
                "vtx_power_mw":  _parse_float(row.get("vtx_power_mw\\"), 0),
                "distance_m":    row.get("distance _m", ""),
                "environment":   row.get("environment", ""),
                "obstacles":     row.get("obtacles", ""),
                "floor_diff":    _parse_int(row.get("floor_diff")),
                "notes":         row.get("notes", ""),
            }
    return out


def is_positive(row):
    v = row["drone_freq_mhz"].strip().lower()
    return v not in ("", "none")


def aggregate(rows):
    tp = sum(r["tp"]       for r in rows)
    fn = sum(r["fn"]       for r in rows)
    fp = sum(r["fp_count"] for r in rows)
    pos = sum(1 for r in rows if is_positive(r))
    neg = sum(1 for r in rows if not is_positive(r))

    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall    = tp / (tp + fn) if (tp + fn) else float("nan")
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else float("nan")

    return {
        "n":         len(rows),
        "n_pos":     pos,
        "n_neg":     neg,
        "tp":        tp,
        "fn":        fn,
        "fp":        fp,
        "precision": precision,
        "recall":    recall,
        "f1":        f1,
    }


def fmt_pct(x, decimals=1):
    if x != x:
        return "  n/a"
    return f"{x*100:>{3+decimals+1}.{decimals}f}%"
