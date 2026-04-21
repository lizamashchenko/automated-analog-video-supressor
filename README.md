# Analog Video Suppressor

Detects analog FPV drone video transmitters by scanning the RF spectrum with a HackRF One and classifying wideband signals as PAL/NTSC analog video.

## How it works

The detection pipeline has three stages:

**1. Coarse scan** — the SDR sweeps from 100 MHz to 6 GHz in 20 MHz steps. At each step it collects `wide_sampling_num` IQ buffers and builds an averaged power spectrum. A plateau detector looks for flat-topped wideband lobes (3–10 MHz wide) characteristic of FM-modulated analog video. A frequency must produce a plateau in at least `required_ratio` of the scans to be confirmed.

**2. Classification** — confirmed plateau frequencies are passed to one of three classifiers, each operating on the FM-demodulated baseband signal and voting across multiple sample buffers:

| Classifier | What it looks for |
|---|---|
| `harmonic` | Peaks at harmonics of the 15.625 kHz PAL line rate in the demodulated spectrum |
| `cyclo` | Same harmonic structure but using a cyclostationary SNR ratio test |
| `autocorr` | Autocorrelation peak at the lag corresponding to one video line period |

**3. Decision** — if the classifier accumulates enough votes across the sample buffers it logs a confirmed analog video detection.

## Project structure

```
full_spectrum_detection.py   # main entry point
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
```

## Requirements

- Python 3.12+
- HackRF One + SoapySDR with the HackRF driver
- `numpy`, `scipy`

## Usage

```bash
# Run with config.toml defaults
python full_spectrum_detection.py

# Override classifier
python full_spectrum_detection.py --classifier cyclo

# Override device — replay a recorded sweep
python full_spectrum_detection.py --device file \
    --file-path /path/to/sweep/iq.bin \
    --metadata-path /path/to/sweep/metadata.csv

# Named log folder + higher verbosity
python full_spectrum_detection.py --run-name wall_test --verbosity 3

# All overrides together
python full_spectrum_detection.py \
    --device file \
    --file-path /path/to/iq.bin \
    --metadata-path /path/to/metadata.csv \
    --classifier harmonic \
    --run-name my_experiment \
    --verbosity 4
```

### CLI arguments

| Argument | Values | Description |
|---|---|---|
| `--classifier` | `harmonic` `cyclo` `autocorr` | Classifier to use |
| `--device` | `hackrf` `file` | Device source |
| `--file-path` | path | IQ binary file (required with `--device file`) |
| `--metadata-path` | path | Metadata CSV (required with `--device file`) |
| `--run-name` | string | Name for the log subfolder (default: timestamp) |
| `--verbosity` | `1`–`4` | Log detail level (see below) |

Any argument not provided falls back to the value in `config.toml`.

## Configuration

All parameters live in `config.toml`. CLI arguments take priority over config values.

Key sections:

| Section | Controls |
|---|---|
| `[logging]` | Output directory, verbosity level |
| `[sdr]` | Sample rate, gain, frequency range, buffer size |
| `[device]` | Device type and file paths for replay mode |
| `[fft]` | FFT size |
| `[scan]` | Number of samples per frequency step |
| `[plateau]` | Detection thresholds for the wideband lobe finder |
| `[demod]` | Minimum sample count required before classifying |
| `[detection]` | Which classifier to use |
| `[classifier.harmonic]` | Harmonic classifier thresholds |
| `[classifier.cyclo]` | Cyclostationary classifier thresholds |
| `[classifier.autocorr]` | Autocorrelation classifier thresholds |

## Logging

Logs are written to `{base_dir}/{run_name}/`. The `base_dir` is set in `[logging]` in `config.toml`; `run_name` defaults to a UTC timestamp.

### Verbosity levels

| Level | What gets logged |
|---|---|
| `1` | Errors (zero buffer, queue overflow, invalid bins) + `confirmed_plateau.log` + `video_detections.log` |
| `2` | Level 1 + plateau confirmed/rejected and video confirmed/rejected decisions in `events.log` |
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

`utils/iq_capture.py --base-dir <output_dir>` is a standalone script that records a full 100 MHz–6 GHz sweep to disk as a flat binary IQ file plus a CSV metadata file. The result can be replayed with `--device file`.

```bash
python utils/iq_capture.py --base-dir "home/iq_samples"
# writes to home/iq_samples/sweep_<timestamp>/iq.bin + metadata.csv
```
