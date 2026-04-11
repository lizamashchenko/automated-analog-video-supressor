import argparse
import SoapySDR
from SoapySDR import *
import numpy as np
import time

from utils.config import load as load_config
from utils.logger import SDRLogger
from rf_devices.hackrf_device import HackRFDevice
from rf_devices.file_devicie import FileDevice
from sdr_reader.reader_runner import SDRReader
from plateau_detector.plateau_detector import PlateauDetector

from video_classifiers.harmonic_classifier import HarmonicClassifier
from video_classifiers.cyclo_classifier import CycloClassifier
from video_classifiers.autocorrelation_classifier import AutocorrClassifier

from utils.spectrum_manipulation import compute_power_spectrum, get_freq_key

# TODO
# fix cluster width detection logic -> allow gaps DONE
# fix logging (log all events, basically move from console to a log file) DONE
# add threading as we are getting stuck at computationally heavy bits (2.4) DONE BUG FIX
# confidence over time DONE
# fix demodulation peak detection logic DONE
# add average from previous scans DONE
# clean code DONE
# limit maximums, for jammer detection DONE
# add debug mode to save time DONE
# global config, normal exit DONE


# make an application
# introduce overlap
# adaptive thresholds
# no tagged freq, can read old samples

# -----------------------------
# CONFIGURATION
# -----------------------------

parser = argparse.ArgumentParser(description="Full-spectrum FPV drone detector")
parser.add_argument("--classifier", choices=["harmonic", "cyclo", "autocorr"],
                    help="Classifier to use (overrides config)")
parser.add_argument("--device", choices=["hackrf", "file"],
                    help="Device type (overrides config)")
parser.add_argument("--file-path", metavar="PATH",
                    help="IQ binary file path (required when --device=file)")
parser.add_argument("--metadata-path", metavar="PATH",
                    help="Metadata CSV path (required when --device=file)")
parser.add_argument("--run-name", metavar="NAME",
                    help="Name for this run's log folder (default: timestamp)")
parser.add_argument("--verbosity", type=int, choices=[1, 2, 3, 4], metavar="1-4",
                    help="Log detail level (overrides config)")
parser.add_argument("--min-freq", type=float, metavar="HZ",
                    help="Start frequency in Hz (overrides config)")
parser.add_argument("--max-freq", type=float, metavar="HZ",
                    help="End frequency in Hz (overrides config)")
parser.add_argument("--sweeps", type=int, default=0, metavar="N",
                    help="Number of full sweeps to run, 0 = run forever (default: 0)")
args = parser.parse_args()

cfg = load_config()

# CLI overrides
if args.device:
    cfg["device"]["type"] = args.device
if args.file_path:
    cfg["device"]["file_path"] = args.file_path
if args.metadata_path:
    cfg["device"]["metadata_path"] = args.metadata_path
if args.classifier:
    cfg["detection"]["active_classifier"] = args.classifier
if args.verbosity:
    cfg["logging"]["verbosity"] = args.verbosity
if args.min_freq:
    cfg["sdr"]["min_freq"] = args.min_freq
if args.max_freq:
    cfg["sdr"]["max_freq"] = args.max_freq

SAMPLE_RATE  = cfg["sdr"]["sample_rate"]
LNA_GAIN     = cfg["sdr"]["lna_gain"]
VGA_GAIN     = cfg["sdr"]["vga_gain"]
MIN_FREQ     = cfg["sdr"]["min_freq"]
MAX_FREQ     = cfg["sdr"]["max_freq"]
BUFFER_SIZE  = cfg["sdr"]["buffer_size"]

FFT_SIZE     = cfg["fft"]["fft_size"]

WIDE_SAMPLING_NUM    = cfg["scan"]["wide_sampling_num"]
PLATEU_REQUIRED_HITS = int(WIDE_SAMPLING_NUM * cfg["plateau"]["required_ratio"])
FREQ_TOLERANCE       = cfg["plateau"]["freq_tolerance"]

MAX_SAMPLES_PER_PLATEAU = cfg["demod"]["max_samples_per_plateau"]
DEMOD_REQUIRED_HITS     = cfg["demod"]["required_hits"]

# Data structures
class ScanState:
    def __init__(self):
        self.avg_power = None
        self.avg_power_map = {}
        self.plateau_map = {}

# Detector
# build spectrum -> detect plateau -> demodulate -> analyze demodulated signal
def fpv_detector():
    state = ScanState()
    current_freq = MIN_FREQ

    # coarse plateau scan
    while current_freq < MAX_FREQ:
        key = get_freq_key(current_freq)

        if key in state.avg_power_map:
            state.avg_power = state.avg_power_map[key].copy()
        else:
            state.avg_power = None

        detections = []
        all_samples = []
        device.tune(current_freq)

        # scan WIDE_SAMPLING_NUM times, to let SDR stabilize
        for _ in range(WIDE_SAMPLING_NUM):
            samples = reader.get_samples()

            if samples is None:
                print("ZERO BUFFER DETECTED")
                log.log_event(
                    "ZERO_BUFFER",
                    "All samples are zero",
                    level=1,
                    freq=current_freq
                )
                continue

            power = compute_power_spectrum(samples, state)
            plateaus = pl_detector.detect(power, current_freq)
            log.print_spectrum_bar(avg_power=state.avg_power, center_freq=current_freq)
            all_samples.append(samples)
            if plateaus:
                detections.append((samples, plateaus))

        plateau = pl_detector.validate(detections)

        if not plateau:
            if len(detections) > 0:
                log.log_event(
                    "PLATEAU_REJECTED",
                    "Not enough hits",
                    level=2,
                    hits=len(detections),
                    required=PLATEU_REQUIRED_HITS,
                    freq=current_freq
                )
            current_freq += SAMPLE_RATE
            continue

        plateau["samples"] = all_samples
        # log events
        log.log_confirmed_plateau(plateau["center_freq"], plateau["bandwidth"], len(detections))
        log.log_event(
            "PLATEAU_CONFIRMED",
            "Wideband signal detected",
            level=2,
            freq=plateau["center_freq"],
            bw=plateau["bandwidth"],
            hits=len(detections)
        )
        print(f"Detected signal bandwidth: {plateau['bandwidth']} MHz")
        print(f"Detected center frequency: {plateau['center_freq']} MHz")
        print(f"Number of hits: {len(detections):.2f} MHz")

        # update globals
        pl_detector.update_map(state.plateau_map, plateau)
        if state.avg_power is not None:
            state.avg_power_map[key] = state.avg_power.copy()
        current_freq += SAMPLE_RATE

    # proceed to demodulation check
    for key, samples_list in state.plateau_map.items():

        if len(samples_list) < MAX_SAMPLES_PER_PLATEAU:
            continue

        center_freq = key * FREQ_TOLERANCE
        result = classifier.classify(samples_list, SAMPLE_RATE, center_freq)

        print(f"[{center_freq/1e6:.1f} MHz] {classifier.name}: {result['score']}")
        if result["confirmed"]:
            print("ANALOG VIDEO CONFIRMED")

            log.log_video_detection(center_freq, result["score"], len(samples_list))
            log.log_event(
                "VIDEO_CONFIRMED",
                f"{classifier.name} confirmed video",
                level=2,
                freq=center_freq,
                score=result["score"]
            )
            log.log_video_samples(center_freq, samples_list)
        else:
            log.log_event(
                "VIDEO_REJECTED",
                f"{classifier.name} rejected video",
                level=2,
                freq=center_freq,
                score=result["score"]
            )
    print("------------------------------")


# -----------------------------
# DEVICE SETUP
# -----------------------------

log = SDRLogger(
    base_log_dir=cfg["logging"]["base_dir"],
    run_name=args.run_name,
    sample_rate=SAMPLE_RATE,
    verbosity=cfg["logging"]["verbosity"]
)

dev_cfg = cfg["device"]
if dev_cfg["type"] == "hackrf":
    device = HackRFDevice(
        sample_rate=SAMPLE_RATE,
        lna_gain=LNA_GAIN,
        vga_gain=VGA_GAIN
    )
elif dev_cfg["type"] == "file":
    device = FileDevice(
        filepath=dev_cfg["file_path"],
        metadata_path=dev_cfg["metadata_path"],
        sample_rate=SAMPLE_RATE
    )
else:
    raise ValueError(f"Unknown device type: {dev_cfg['type']!r}. Use 'hackrf' or 'file'.")

reader = SDRReader(device, buffer_size=BUFFER_SIZE, logger=log)

pl_cfg = cfg["plateau"]
pl_detector = PlateauDetector(
    sample_rate=SAMPLE_RATE,
    fft_size=FFT_SIZE,
    wide_sampling_num=WIDE_SAMPLING_NUM,
    freq_tolerance=pl_cfg["freq_tolerance"],
    above_noise_threshold=pl_cfg["above_noise_threshold"],
    edge_drop_level=pl_cfg["edge_drop_level"],
    min_lobe_size=pl_cfg["min_lobe_size"],
    lobe_merge_gap=pl_cfg["lobe_merge_gap"],
    min_video_width=pl_cfg["min_video_width"],
    max_video_width=pl_cfg["max_video_width"],
    plateau_required_ratio=pl_cfg["required_ratio"],
    logger=log
)

active = cfg["detection"]["active_classifier"]
if active == "harmonic":
    h = cfg["classifier"]["harmonic"]
    classifier = HarmonicClassifier(
        required_hits=h["required_hits"],
        required_votes=h["required_votes"],
        threshold_db=h["threshold_db"],
        target_freq=h["target_freq"],
        sync_band=h["sync_band"],
        harmonics=h["harmonics"],
        logger=log
    )
elif active == "cyclo":
    c = cfg["classifier"]["cyclo"]
    classifier = CycloClassifier(
        sample_rate=SAMPLE_RATE,
        fft_size=FFT_SIZE,
        ratio_threshold=c["ratio_threshold"],
        score_threshold=c["score_threshold"],
        required_votes=c["required_votes"],
        target_freq=c["target_freq"],
        harmonics=c["harmonics"],
        logger=log
    )
elif active == "autocorr":
    a = cfg["classifier"]["autocorr"]
    classifier = AutocorrClassifier(
        sample_rate=SAMPLE_RATE,
        decimation=a["decimation"],
        line_freq=a["line_freq"],
        lag_tolerance=a["lag_tolerance"],
        peak_threshold=a["peak_threshold"],
        required_votes=a["required_votes"],
        logger=log
    )
else:
    raise ValueError(f"Unknown classifier: {active!r}. Use 'harmonic', 'cyclo', or 'autocorr'.")

reader.start()

try:
    sweep = 0
    while args.sweeps == 0 or sweep < args.sweeps:
        fpv_detector()
        sweep += 1
except KeyboardInterrupt:
    pass
finally:
    reader.stop()
    device.close()
