#!/usr/bin/env bash
set -e

# ── Usage ────────────────────────────────────────────────────────────────
# ./scenarios/run_dataset.sh --classifier <name> --verbosity <N> [options]
#
# Runs a single classifier over the full dataset.
# ─────────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $0 --classifier <name> --verbosity <N> [options]

Run a single classifier over every sample in the dataset.

Required:
  --classifier <name>       Classifier to run (harmonic | cyclo | autocorr)
  --verbosity <0-4>         Log verbosity level

Optional:
  --metadata <PATH>         Metadata CSV (default: /home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv)
  --iq-root <DIR>           IQ recordings root (default: /home/liza/UCU/diploma/dataset_original/iq_recordings)
  --column <NAME>           Metadata column for folder names (default: iq_folder)
  --sweeps <N>              Sweeps per sample (default: 1)
  -h, --help                Show this help and exit

Examples:
  $0 --classifier cyclo --verbosity 3
  $0 --classifier harmonic --verbosity 2 --sweeps 2
EOF
}

CLASSIFIER=""
VERBOSITY=""
METADATA_CSV=/home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv
IQ_ROOT=/home/liza/UCU/diploma/dataset_original/iq_recordings
COLUMN=iq_folder
SWEEPS=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --classifier) CLASSIFIER="$2"; shift 2 ;;
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

if [[ -z "${CLASSIFIER}" || -z "${VERBOSITY}" ]]; then
    echo "Missing required --classifier and/or --verbosity" >&2
    echo "" >&2
    usage >&2
    exit 2
fi

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
}')

TOTAL=$(echo "${FOLDERS}" | wc -l)
RUN_PREFIX="dataset_${CLASSIFIER}_$(date +%Y%m%d_%H%M%S)"

echo "================================================"
echo " Dataset run"
echo "  classifier : ${CLASSIFIER}"
echo "  verbosity  : ${VERBOSITY}"
echo "  metadata   : ${METADATA_CSV}"
echo "  iq root    : ${IQ_ROOT}"
echo "  column     : ${COLUMN} (idx ${COL_IDX})"
echo "  folders    : ${TOTAL}"
echo "  run prefix : ${RUN_PREFIX}"
echo "================================================"

i=0
FAILED=()
for FOLDER in ${FOLDERS}; do
    i=$((i + 1))
    IQ_BIN="${IQ_ROOT}/${FOLDER}/iq.bin"
    META="${IQ_ROOT}/${FOLDER}/metadata.csv"

    echo ""
    echo "--- [${i}/${TOTAL}] ${FOLDER} ---"

    if [[ ! -f "${IQ_BIN}" || ! -f "${META}" ]]; then
        echo "  SKIP: missing iq.bin or metadata.csv in ${IQ_ROOT}/${FOLDER}"
        FAILED+=("${FOLDER} (missing)")
        continue
    fi

    if ! python3 full_spectrum_detection.py \
        --device file \
        --file-path "${IQ_BIN}" \
        --metadata-path "${META}" \
        --classifier "${CLASSIFIER}" \
        --verbosity "${VERBOSITY}" \
        --sweeps "${SWEEPS}" \
        --run-name "${RUN_PREFIX}_${FOLDER}"; then
        FAILED+=("${FOLDER} (exit $?)")
    fi
done

echo ""
echo "================================================"
echo " Done. logs: logs/${RUN_PREFIX}_*"
if (( ${#FAILED[@]} > 0 )); then
    echo " Failures:"
    for f in "${FAILED[@]}"; do echo "   - ${f}"; done
fi
echo "================================================"

python3 analysis/dataset_results.py \
    --run-prefix "${RUN_PREFIX}" \
    --metadata "${METADATA_CSV}" \
    --logs-base logs
