# Analog Video Suppressor

Detects analog FPV drone video transmitters by scanning the RF spectrum with a HackRF One and classifying wideband signals as PAL/NTSC analog video. Optionally drives a multi-channel jammer when a transmitter is confirmed.

## How it works

The detection pipeline has three stages:

**1. Coarse scan** — the SDR sweeps from 100 MHz to 6 GHz in 20 MHz steps. At each step it collects `wide_sampling_num` IQ buffers and builds an averaged power spectrum. A plateau detector looks for flat-topped wideband lobes (3–10 MHz wide) characteristic of FM-modulated analog video. A frequency must produce a plateau in at least `required_ratio` of the scans to be confirmed.

**2. Classification** — confirmed plateau frequencies are passed to one of three classifiers, each operating on the FM-demodulated baseband signal and voting across multiple sample buffers:

| Classifier | What it looks for |
|---|---|
| `harmonic` | Peaks at harmonics of the 15.625 kHz PAL line rate in the demodulated spectrum |
| `cyclo` | Same harmonic structure but using a cyclostationary SNR ratio test |
| `autocorr` | Autocorrelation peak at the lag corresponding to one video line period |

**3. Decision** — if the classifier accumulates enough votes it logs a confirmed analog video detection and (if enabled) activates the jammer channel covering that frequency.

## Project structure

```
full_spectrum_detection.py   # CLI entry point
config.toml                  # all tunable parameters

rf_devices/
  hackrf_device.py           # live HackRF One via SoapySDR
  file_device.py             # replay recorded sweeps from disk

sdr_reader/
  reader_runner.py           # threaded IQ reader with queue

plateau_detector/
  plateau_detector.py        # wideband plateau detection on the power spectrum

video_classifiers/
  harmonic_classifier.py
  cyclo_classifier.py
  autocorrelation_classifier.py

utils/
  config.py                  # TOML loader
  logger.py                  # structured logging with verbosity levels
  spectrum_manipulation.py   # FFT / power spectrum helpers
  iq_capture.py              # standalone script to record a sweep to disk
  jammer.py                  # serial driver for the suppressor board
  plot_iq.py, plot_signal.py # offline visualization helpers

web/
  app.py                     # Flask server — live web UI
  templates/, static/        # UI assets

scenarios/                   # batch jobs over the dataset
  run_dataset.sh             # one classifier × every recording
  run_latest.sh              # all classifiers × N most-recent recordings
  tune_all.sh                # run every classifier + grid-search thresholds

analysis/                    # post-run metric and tuning tools
  dataset_results.py         # build per-sweep TP/FP/FN CSV from a run
  tune_classifier.py         # grid-search classifier thresholds
  eval_plateau.py            # plateau-detector Pd/Pfa
  eval_classifier_metrics.py # classifier Pd/Pfa
  eval_distance.py           # Pd/Pfa vs transmitter distance
  eval_obstruction.py        # Pd/Pfa by obstacle category
  eval_timing.py             # detection-latency analysis
  plot_detections.py, run_summary.py

suppressor_bridge_board/     # PlatformIO firmware for the PC-side Arduino Nano
                             # that bridges USB serial onto the wired link
suppressor_driver_board/     # PlatformIO firmware for the far-end Arduino Nano
                             # that drives the 8 jammer modules
```

## Requirements

- Python 3.12+
- HackRF One + SoapySDR with the HackRF driver
- `numpy`, `scipy`, `flask`, `pyserial`

## Quickstart

```bash
# 1. point config.toml [dataset] at your local recordings (one-time)
# 2. live detection from the HackRF
python full_spectrum_detection.py --device hackrf

# OR replay a recorded sweep
python full_spectrum_detection.py --device file \
    --file-path /path/to/sweep/iq.bin \
    --metadata-path /path/to/sweep/metadata.csv

# OR open the web UI
python web/app.py --port 5000
```

## Configuration

Everything tunable is in [`config.toml`](config.toml). CLI arguments and web-UI form fields override values there.

Key sections:

| Section | Controls |
|---|---|
| `[logging]` | Output directory, verbosity level (0–4) |
| `[dataset]` | `metadata_csv` + `iq_root` — single source of truth for dataset paths used by `scenarios/` and `analysis/` |
| `[sdr]` | Sample rate, gain, frequency range, buffer size |
| `[device]` | Active device (`hackrf` / `file`) and replay paths |
| `[fft]` | FFT size |
| `[scan]` | Buffers per coarse-scan step |
| `[plateau]` | Wideband lobe-detection thresholds |
| `[demod]` | Min sample buffers required before classifying |
| `[detection]` | Active classifier (`harmonic` / `cyclo` / `autocorr`) |
| `[classifier.*]` | Per-classifier thresholds |
| `[jammer]` | Serial port + per-channel frequency ranges for the suppressor board |

## Live detection

### CLI — `full_spectrum_detection.py`

```bash
# config defaults
python full_spectrum_detection.py

# pick a classifier
python full_spectrum_detection.py --classifier cyclo

# replay a recorded sweep
python full_spectrum_detection.py --device file \
    --file-path /path/to/sweep/iq.bin \
    --metadata-path /path/to/sweep/metadata.csv

# named log folder, debug verbosity, single sweep
python full_spectrum_detection.py --run-name wall_test --verbosity 3 --sweeps 1
```

| Argument | Values | Description |
|---|---|---|
| `--classifier` | `harmonic` `cyclo` `autocorr` | Classifier to use |
| `--device` | `hackrf` `file` | Device source |
| `--file-path` | path | IQ binary file (required with `--device file`) |
| `--metadata-path` | path | Metadata CSV (required with `--device file`) |
| `--run-name` | string | Name for the log subfolder (default: timestamp) |
| `--verbosity` | `0`–`4` | Log detail level (see below) |
| `--min-freq` / `--max-freq` | Hz | Override scan range from config |
| `--sweeps` | int | How many full sweeps to run (`0` = forever, default) |

Anything not provided falls back to `config.toml`.

### Web UI — `web/app.py`

```bash
python web/app.py --port 5000
# open http://127.0.0.1:5000
```

Features:
- Configure device, classifier, frequency range, sweeps, verbosity, and run name from the sidebar
- Live spectrum waterfall + per-window FFT
- Confirmed-plateau and video-detection tables
- **Detection alert**: every confirmed video transmission triggers a pulsing red banner + an audible two-tone beep — the warning you don't want to miss

## Logging

Logs are written to `{base_dir}/{run_name}/`. `base_dir` is set in `[logging]`; `run_name` defaults to a UTC timestamp.

### Verbosity levels

| Level | What gets logged |
|---|---|
| `0` | **stdout / UI**: only errors + confirmed video detections + jammer events. **No log files written.** Use for quiet long-running deployments. |
| `1` | Errors + `confirmed_plateau.log` + `video_detections.log` |
| `2` | Level 1 + plateau and video confirmed/rejected decisions in `events.log` |
| `3` | Level 2 + per-component debug files: `plateau_debug.log`, `harmonic_debug.log`, `cyclo_debug.log`, `autocorr_debug.log` |
| `4` | Level 3 + raw IQ samples saved as `.npy` files in `samples/` for every confirmed video hit |

### Output files

```
logs/my_run/
├── events.log               # errors (L1+) and decisions (L2+)
├── confirmed_plateau.log    # timestamp, center_freq, bandwidth, hit_count
├── video_detections.log     # timestamp, center_freq, score, sample_count
├── plateau_debug.log        # cluster stats per FFT window          (L3+)
├── harmonic_debug.log       # per-frequency classifier results      (L3+)
├── cyclo_debug.log          #   "                                   (L3+)
├── autocorr_debug.log       #   "                                   (L3+)
└── samples/                 # {freq}MHz_{time}.npy per confirmed hit (L4+)
```

## Recording a sweep

`utils/iq_capture.py` records a full 100 MHz–6 GHz sweep to disk as a flat binary IQ file plus a CSV metadata file. The result can be replayed with `--device file` or added to the dataset.

```bash
python utils/iq_capture.py                    # writes under config [dataset].iq_root
python utils/iq_capture.py --base-dir /tmp/x  # custom output dir
# → <base-dir>/sweep_<timestamp>/iq.bin + metadata.csv
```

## Running the dataset (`scenarios/`)

These shell scripts batch-run the detector across many recordings and feed the logs into `analysis/`. Dataset paths default to `config.toml [dataset]`; override per-run with `--metadata` / `--iq-root` if needed.

```bash
# one classifier across every recording in the dataset
./scenarios/run_dataset.sh --classifier cyclo --verbosity 2

# all three classifiers across the most-recent N recordings (post-capture sanity check)
./scenarios/run_latest.sh --n-last 5

# run all three classifiers + grid-search every threshold
./scenarios/tune_all.sh
./scenarios/tune_all.sh --exclude-freqs "762,2400-2500"  # skip known-bad bands when scoring FPs
```

Each scenario writes per-recording log folders under `logs/` with a shared run prefix, then automatically generates a `_results.csv`.

## Analysis (`analysis/`)

Each tool reads `_results.csv` files written by `dataset_results.py` (or runs from scratch). All defaults are sourced from `config.toml [dataset]` — pass `--meta` / `--metadata` to override.

| Tool | What it reports |
|---|---|
| `dataset_results.py` | Per-sweep TP/FP/FN CSV (called automatically by `scenarios/`) |
| `eval_classifier_metrics.py` | Per-classifier Pd / Pfa across the dataset |
| `eval_plateau.py` | Plateau-detector Pd / Pfa / candidate-reduction / voting-rejection |
| `eval_distance.py` | Pd / Pfa vs transmitter distance |
| `eval_obstruction.py` | Pd / Pfa by obstacle category (line-of-sight, panel wall, brick walls, …) |
| `eval_timing.py` | Detection latency |
| `tune_classifier.py` | Grid-search classifier thresholds against a saved run |
| `plot_detections.py`, `run_summary.py` | Quick visualizations |

Example:

```bash
# Pd/Pfa for the most recent run
python -m analysis.eval_classifier_metrics

# Distance breakdown for a specific run timestamp
python -m analysis.eval_distance --run 20260424_201338
```

## Jammer / suppressor driver board

When `[jammer].enabled = true` in `config.toml`, every confirmed video detection activates the jammer channel whose frequency range covers that detection. Channels stay on for `hold_seconds` and re-arm if the same band is seen again. While a channel is active, the scanner skips the corresponding band to avoid feedback.

| `[jammer]` field | Meaning |
|---|---|
| `enabled` | Master switch — when false the detector runs without driving the board |
| `port`, `baud` | Serial connection to the Arduino driver |
| `modules` | Number of jammer channels (must equal `len(ranges)`) |
| `hold_seconds` | How long a channel stays on per detection |
| `ranges` | Per-channel `{ min, max }` frequency bands in Hz |

The serial path runs through two Arduino Nanos: [`suppressor_bridge_board/`](suppressor_bridge_board/) sits on the PC end and forwards USB-serial bytes onto a single twisted pair (lifted from a piece of Ethernet cable), and [`suppressor_driver_board/`](suppressor_driver_board/) sits at the antenna site and switches the 8 jammer channels.

### Power-up order

The bridge board (PC end) **must be powered before** the detector opens its serial port — wait **5 seconds after plugging it in** to give the firmware time to initialise its software UART and flush the link before starting `full_spectrum_detection.py` or `web/app.py`. Starting the detector against a not-yet-ready bridge will leak the first few bytes of the channel bitmask.

## Branch policy

Active development on `main` stops at the **thesis submission deadline**. After that point `main` is frozen as the as-submitted snapshot for the diploma — bug fixes and any further work continue on the **`post-thesis`** branch. Cut new feature branches off `post-thesis`, not `main`.
