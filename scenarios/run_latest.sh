#!/usr/bin/env bash
set -e

# ── Usage ────────────────────────────────────────────────────────────────
# ./scenarios/run_latest.sh <n_last> [verbosity] [metadata_csv] [iq_root] [column] [sweeps]
#
# Runs all 3 classifiers on the last N samples from the metadata CSV.
# Quick sanity check after adding new data to the dataset.
#
# Examples:
#   ./scenarios/run_latest.sh 5
#   ./scenarios/run_latest.sh 3 2
# ─────────────────────────────────────────────────────────────────────────

N_LAST=${1:?Usage: $0 <n_last> [verbosity] [metadata_csv] [iq_root] [column] [sweeps]}
VERBOSITY=${2:-2}
METADATA_CSV=${3:-/home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv}
IQ_ROOT=${4:-/home/liza/UCU/diploma/dataset_original/iq_recordings}
COLUMN=${5:-iq_folder}
SWEEPS=${6:-1}

CLASSIFIERS=(cyclo autocorr harmonic)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

if [[ ! -f "${METADATA_CSV}" ]]; then
    echo "metadata csv not found: ${METADATA_CSV}" >&2
    exit 1
fi

COL_IDX=$(head -n 1 "${METADATA_CSV}" | awk -F, -v col="${COLUMN}" '{
    for (i = 1; i <= NF; i++) {
        gsub(/^[ \t"]+|[ \t"\r]+$/, "", $i)
        if ($i == col) { print i; exit }
    }
}')

if [[ -z "${COL_IDX}" ]]; then
    echo "column '${COLUMN}' not found in ${METADATA_CSV}" >&2
    echo "header: $(head -n 1 "${METADATA_CSV}")" >&2
    exit 1
fi

FOLDERS=$(tail -n +2 "${METADATA_CSV}" | awk -F, -v idx="${COL_IDX}" '{
    gsub(/^[ \t"]+|[ \t"\r]+$/, "", $idx)
    if ($idx != "") print $idx
}' | tail -n "${N_LAST}")

TOTAL=$(echo "${FOLDERS}" | wc -l)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "================================================"
echo " Run latest ${N_LAST} samples (all classifiers)"
echo "  verbosity  : ${VERBOSITY}"
echo "  metadata   : ${METADATA_CSV}"
echo "  iq root    : ${IQ_ROOT}"
echo "  column     : ${COLUMN} (idx ${COL_IDX})"
echo "  folders    : ${TOTAL}"
echo "  timestamp  : ${TIMESTAMP}"
echo "================================================"

declare -A RUN_PREFIXES

for CLASSIFIER in "${CLASSIFIERS[@]}"; do
    RUN_PREFIX="latest${N_LAST}_${CLASSIFIER}_${TIMESTAMP}"
    RUN_PREFIXES[${CLASSIFIER}]="${RUN_PREFIX}"

    echo ""
    echo "╔══════════════════════════════════════════════╗"
    echo "║  Running: ${CLASSIFIER}"
    echo "║  Prefix:  ${RUN_PREFIX}"
    echo "╚══════════════════════════════════════════════╝"
    echo ""

    i=0
    FAILED=()
    for FOLDER in ${FOLDERS}; do
        i=$((i + 1))
        IQ_BIN="${IQ_ROOT}/${FOLDER}/iq.bin"
        META="${IQ_ROOT}/${FOLDER}/metadata.csv"

        echo "  [${i}/${TOTAL}] ${FOLDER}"

        if [[ ! -f "${IQ_BIN}" || ! -f "${META}" ]]; then
            echo "    SKIP: missing files"
            FAILED+=("${FOLDER}")
            continue
        fi

        if ! python3 full-spectrum-detection.py \
            --device file \
            --file-path "${IQ_BIN}" \
            --metadata-path "${META}" \
            --classifier "${CLASSIFIER}" \
            --verbosity "${VERBOSITY}" \
            --sweeps "${SWEEPS}" \
            --run-name "${RUN_PREFIX}_${FOLDER}" 2>&1 | tail -1; then
            FAILED+=("${FOLDER}")
        fi
    done

    echo ""
    if (( ${#FAILED[@]} > 0 )); then
        echo "  Failures: ${#FAILED[@]}"
        for f in "${FAILED[@]}"; do echo "    - ${f}"; done
    fi

    python3 analysis/dataset_results.py \
        "${RUN_PREFIX}" \
        --metadata "${METADATA_CSV}" \
        --logs-base logs
done

echo ""
echo "================================================"
echo " Done. Run prefixes:"
for CLASSIFIER in "${CLASSIFIERS[@]}"; do
    echo "   ${CLASSIFIER}: ${RUN_PREFIXES[${CLASSIFIER}]}"
done
echo "================================================"
