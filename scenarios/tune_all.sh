#!/usr/bin/env bash
set -e

# ── Usage ────────────────────────────────────────────────────────────────
# ./scenarios/tune_all.sh [options]
#
# Runs all 3 classifiers over the dataset with verbosity=3, then
# calls tune_classifier.py on each to suggest better parameters.
# ─────────────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
Usage: $0 [options]

Run every classifier over the dataset and grid-search for better thresholds.

Optional:
  --metadata <PATH>          Metadata CSV (default: /home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv)
  --iq-root <DIR>            IQ recordings root (default: /home/liza/UCU/diploma/dataset_original/iq_recordings)
  --exclude-freqs <SPEC>     Comma-separated MHz freqs/ranges to exclude from FP count
                             (e.g. '762,1100-1300,2400-2500')
  --exclude-sweeps <SPEC>    Exclude FPs from sweeps matching metadata conditions
                             Format: 'key=val,key=val' (AND); groups separated by ';' (OR)
                             (e.g. 'drone_freq=1240,distance _m=1.5')
  -h, --help                 Show this help and exit

Examples:
  $0
  $0 --metadata /path/meta.csv --iq-root /path/iq
  $0 --exclude-freqs "762,2400-2500" --exclude-sweeps "drone_freq=1240,distance _m=1.5"
EOF
}

METADATA_CSV=/home/liza/UCU/diploma/dataset_original/iq_recording_meta.csv
IQ_ROOT=/home/liza/UCU/diploma/dataset_original/iq_recordings
EXCLUDE_FREQS=""
EXCLUDE_SWEEPS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --metadata)        METADATA_CSV="$2"; shift 2 ;;
        --iq-root)         IQ_ROOT="$2"; shift 2 ;;
        --exclude-freqs)   EXCLUDE_FREQS="$2"; shift 2 ;;
        --exclude-sweeps)  EXCLUDE_SWEEPS="$2"; shift 2 ;;
        -h|--help)         usage; exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            echo "" >&2
            usage >&2
            exit 2
            ;;
    esac
done

VERBOSITY=3
SWEEPS=1
COLUMN=iq_folder
CLASSIFIERS=(cyclo autocorr harmonic)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}/.."

if [[ ! -f "${METADATA_CSV}" ]]; then
    echo "metadata csv not found: ${METADATA_CSV}" >&2
    exit 1
fi

# ── Resolve folders from metadata CSV ────────────────────────────────────

COL_IDX=$(head -n 1 "${METADATA_CSV}" | awk -F, -v col="${COLUMN}" '{
    for (i = 1; i <= NF; i++) {
        gsub(/^[ \t"]+|[ \t"\r]+$/, "", $i)
        if ($i == col) { print i; exit }
    }
}')

if [[ -z "${COL_IDX}" ]]; then
    echo "column '${COLUMN}' not found in ${METADATA_CSV}" >&2
    exit 1
fi

FOLDERS=$(tail -n +2 "${METADATA_CSV}" | awk -F, -v idx="${COL_IDX}" '{
    gsub(/^[ \t"]+|[ \t"\r]+$/, "", $idx)
    if ($idx != "") print $idx
}')

TOTAL=$(echo "${FOLDERS}" | wc -l)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "================================================"
echo " Tune all classifiers"
echo "  metadata      : ${METADATA_CSV}"
echo "  iq root       : ${IQ_ROOT}"
echo "  folders       : ${TOTAL}"
echo "  verbosity     : ${VERBOSITY}"
echo "  timestamp     : ${TIMESTAMP}"
if [[ -n "${EXCLUDE_FREQS}" ]]; then
    echo "  exclude freqs : ${EXCLUDE_FREQS}"
fi
if [[ -n "${EXCLUDE_SWEEPS}" ]]; then
    echo "  exclude sweeps: ${EXCLUDE_SWEEPS}"
fi
echo "================================================"
echo ""

# ── Run each classifier ─────────────────────────────────────────────────

declare -A RUN_PREFIXES

for CLASSIFIER in "${CLASSIFIERS[@]}"; do
    RUN_PREFIX="dataset_${CLASSIFIER}_${TIMESTAMP}"
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

    # Generate results CSV
    python3 analysis/dataset_results.py \
        --run-prefix "${RUN_PREFIX}" \
        --metadata "${METADATA_CSV}" \
        --logs-base logs
done

# ── Tune each classifier ────────────────────────────────────────────────

echo ""
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              Parameter Tuning Results                ║"
echo "╚══════════════════════════════════════════════════════╝"

for CLASSIFIER in "${CLASSIFIERS[@]}"; do
    RUN_PREFIX="${RUN_PREFIXES[${CLASSIFIER}]}"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ${CLASSIFIER^^}"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    TUNE_ARGS=(
        --run-prefix "${RUN_PREFIX}"
        --classifier "${CLASSIFIER}"
        --metadata "${METADATA_CSV}"
        --logs-base logs
        --top 10
    )

    if [[ -n "${EXCLUDE_FREQS}" ]]; then
        TUNE_ARGS+=(--exclude-freqs "${EXCLUDE_FREQS}")
    fi
    if [[ -n "${EXCLUDE_SWEEPS}" ]]; then
        TUNE_ARGS+=(--exclude-sweeps "${EXCLUDE_SWEEPS}")
    fi

    python3 analysis/tune_classifier.py "${TUNE_ARGS[@]}"
done

echo ""
echo "================================================"
echo " All done. Run prefixes:"
for CLASSIFIER in "${CLASSIFIERS[@]}"; do
    echo "   ${CLASSIFIER}: ${RUN_PREFIXES[${CLASSIFIER}]}"
done
echo "================================================"
