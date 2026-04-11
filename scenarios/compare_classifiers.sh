#!/bin/bash
# Run all three classifiers on a live HackRF sweep and collect logs for later analysis.
#
# Usage:
#   ./scenarios/compare_classifiers.sh <min_freq_mhz> <max_freq_mhz> <sweeps>
#
# Example:
#   ./scenarios/compare_classifiers.sh 2300 2600 5

set -e

MIN_MHZ=${1:?Usage: $0 <min_freq_mhz> <max_freq_mhz> <sweeps>}
MAX_MHZ=${2:?Usage: $0 <min_freq_mhz> <max_freq_mhz> <sweeps>}
SWEEPS=${3:?Usage: $0 <min_freq_mhz> <max_freq_mhz> <sweeps>}

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
    python3 full-spectrum-detection.py \
        --device hackrf \
        --classifier "${CLASSIFIER}" \
        --min-freq "${MIN_HZ}" \
        --max-freq "${MAX_HZ}" \
        --sweeps "${SWEEPS}" \
        --run-name "${RUN_NAME}_${CLASSIFIER}" \
        --verbosity 4
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
