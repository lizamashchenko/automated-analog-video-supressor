#!/usr/bin/env bash
set -e

CLASSIFIER=${1:?Usage: $0 <classifier> <verbosity> [metadata_csv] [iq_root] [column] [sweeps]}
VERBOSITY=${2:?Usage: $0 <classifier> <verbosity> [metadata_csv] [iq_root] [column] [sweeps]}
METADATA_CSV=${3:-/home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv}
IQ_ROOT=${4:-/home/liza/UCU/diploma/dataset_original/iq_recordings}
COLUMN=${5:-iq_folder}
SWEEPS=${6:-1}

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

    if ! python3 full-spectrum-detection.py \
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
    "${RUN_PREFIX}" \
    --metadata "${METADATA_CSV}" \
    --logs-base logs
