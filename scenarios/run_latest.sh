#!/usr/bin/env bash
set -e

# usage:
# ./scenarios/run_latest.sh --n-last <N> [options]
#
# Runs all 3 classifiers on the last N samples from the metadata CSV.
# Quick sanity check after adding new data to the dataset.

usage() {
    cat <<EOF
Usage: $0 --n-last <N> [options]

Run all classifiers on the last N samples of a dataset.

Required:
  --n-last <N>              Number of most-recent samples to run

Optional:
  --verbosity <0-4>         Log verbosity level (default: 2)
  --metadata <PATH>         Metadata CSV (default: from config.toml [dataset].metadata_csv)
  --iq-root <DIR>           IQ recordings root (default: from config.toml [dataset].iq_root)
  --column <NAME>           Metadata column for folder names (default: iq_folder)
  --sweeps <N>              Sweeps per sample (default: 1)
  -h, --help                Show this help and exit

Examples:
  $0 --n-last 5
  $0 --n-last 3 --verbosity 2
  $0 --n-last 10 --metadata /other/meta.csv --iq-root /other/iq
EOF
}

N_LAST=""
VERBOSITY=2
METADATA_CSV=""
IQ_ROOT=""
COLUMN=iq_folder
SWEEPS=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --n-last)     N_LAST="$2"; shift 2 ;;
        --verbosity)  VERBOSITY="$2"; shift 2 ;;
        --metadata)   METADATA_CSV="$2"; shift 2 ;;
        --iq-root)    IQ_ROOT="$2"; shift 2 ;;
        --column)     COLUMN="$2"; shift 2 ;;
        --sweeps)     SWEEPS="$2"; shift 2 ;;
        -h|--help)    usage; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ -z "${N_LAST}" ]]; then
    echo "Missing required --n-last" >&2
    echo "" >&2
    usage >&2
    exit 2
fi

CLASSIFIERS=(cyclo autocorr harmonic)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

: "${METADATA_CSV:=$(python3 -c "from utils.config import load; print(load()['dataset']['metadata_csv'])")}"
: "${IQ_ROOT:=$(python3 -c "from utils.config import load; print(load()['dataset']['iq_root'])")}"

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
    echo "║  Running: ${CLASSIFIER}"                     ║
    echo "║  Prefix:  ${RUN_PREFIX}"                     ║   
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

        if ! python3 full_spectrum_detection.py \
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
        --run-prefix "${RUN_PREFIX}" \
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
