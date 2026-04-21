#!/usr/bin/env bash
set -e

# ── Usage ────────────────────────────────────────────────────────────────
# ./scenarios/live_compare_classifiers.sh --min-mhz <F> --max-mhz <F> --sweeps <N> [options]
#
# Runs all 3 classifiers against live HackRF input over a frequency window
# and then runs summary + plot analysis.
# ─────────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $0 --min-mhz <F> --max-mhz <F> --sweeps <N> [options]

Run all classifiers live and compare their output.

Required:
  --min-mhz <F>       Start frequency in MHz
  --max-mhz <F>       End frequency in MHz
  --sweeps <N>        Number of sweeps per classifier

Optional:
  --verbosity <0-4>   Log verbosity level (default: 4)
  -h, --help          Show this help and exit

Example:
  $0 --min-mhz 1200 --max-mhz 1300 --sweeps 3
EOF
}

MIN_MHZ=""
MAX_MHZ=""
SWEEPS=""
VERBOSITY=4

while [[ $# -gt 0 ]]; do
    case "$1" in
        --min-mhz)   MIN_MHZ="$2"; shift 2 ;;
        --max-mhz)   MAX_MHZ="$2"; shift 2 ;;
        --sweeps)    SWEEPS="$2"; shift 2 ;;
        --verbosity) VERBOSITY="$2"; shift 2 ;;
        -h|--help)   usage; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "${MIN_MHZ}" || -z "${MAX_MHZ}" || -z "${SWEEPS}" ]]; then
    echo "Missing required --min-mhz, --max-mhz, and/or --sweeps" >&2
    echo "" >&2
    usage >&2
    exit 2
fi

MIN_HZ=$(( MIN_MHZ * 1000000 ))
MAX_HZ=$(( MAX_MHZ * 1000000 ))

RUN_NAME="compare_$(date +%Y%m%d_%H%M%S)"

echo "================================================"
echo " Classifier comparison run: ${RUN_NAME}"
echo " Spectrum : ${MIN_MHZ} – ${MAX_MHZ} MHz"
echo " Sweeps   : ${SWEEPS}"
echo "================================================"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

for CLASSIFIER in harmonic cyclo autocorr; do
    echo ""
    echo "--- Running classifier: ${CLASSIFIER} ---"
    python3 full_spectrum_detection.py \
        --device hackrf \
        --classifier "${CLASSIFIER}" \
        --min-freq "${MIN_HZ}" \
        --max-freq "${MAX_HZ}" \
        --sweeps "${SWEEPS}" \
        --run-name "${RUN_NAME}_${CLASSIFIER}" \
        --verbosity "${VERBOSITY}"
    echo "--- ${CLASSIFIER} done ---"
    sleep 2
done

echo ""
echo "================================================"
echo " All classifiers complete."
echo " Logs: logs/${RUN_NAME}_harmonic/"
echo "       logs/${RUN_NAME}_cyclo/"
echo "       logs/${RUN_NAME}_autocorr/"
echo "================================================"

echo ""
echo "--- Running analysis ---"

python3 analysis/run_summary.py --run-name "${RUN_NAME}"

python3 analysis/plot_detections.py --run-name "${RUN_NAME}"

echo ""
echo "================================================"
echo " Analysis complete."
echo " Plots saved alongside .npy files in samples/."
echo "================================================"
