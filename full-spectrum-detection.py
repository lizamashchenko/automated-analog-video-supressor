import SoapySDR
from SoapySDR import *
import numpy as np
import time

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

# make an application
# introduce overlap
# adaptive thresholds 
# limit maximums, for jammer detection
# no tagged freq, can read old samples 
# add debug mode to save time

# -----------------------------
# PARAMETERS
# -----------------------------

# Hack RF One setup
LNA_GAIN = 32
VGA_GAIN = 32
MIN_FREQ = 5830e6   # Hz
MAX_FREQ = 5850e6   # Hz
SAMPLE_RATE = 20e6  # Hz

# FFT params
FFT_SIZE = 4096
BUFFER_SIZE = 262144

# Coarse scan params
WIDE_SAMPLING_NUM = 10
PLATEU_REQUIRED_RATIO = 0.3
PLATEU_REQUIRED_HITS = int(WIDE_SAMPLING_NUM * PLATEU_REQUIRED_RATIO)

# Demodulation thresholds
MAX_SAMPLES_PER_PLATEAU = 5
DEMOD_REQUIRED_HITS = 3
FREQ_TOLERANCE = 2e6  # Hz

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

    # coarse plateu scan
    while current_freq < MAX_FREQ:
        key = get_freq_key(current_freq)

        if key in state.avg_power_map:
            state.avg_power = state.avg_power_map[key].copy()
        else:
            state.avg_power = None

        detections = []

        device.tune(current_freq)

        # scan WIDE_SAMPLING_NUM times, to let SDR stabilize
        for _ in range(WIDE_SAMPLING_NUM):
            samples = reader.get_samples()

            if samples is None:
                print("ZERO BUFFER DETECTED")
                log.log_event(
                    "ZERO_BUFFER",
                    "All samples are zero",
                    freq=current_freq
                )
                continue

            power = compute_power_spectrum(samples, state)    
            plateaus = pl_detector.detect(power, current_freq)
            log.print_spectrum_bar(avg_power=state.avg_power, center_freq=current_freq)

            if plateaus:
                detections.append((samples, plateaus))

        plateau = pl_detector.validate(detections)

        if not plateau:
            if len(detections) > 0:
                log.log_event (
                        "PLATEAU_REJECTED",
                        "Not enough hits",
                        hits=len(detections),
                        required=PLATEU_REQUIRED_HITS,
                        freq=current_freq
                )
            current_freq += SAMPLE_RATE
            continue
        
        # log events
        log.log_confirmed_plateau(plateau["center_freq"], plateau["bandwidth"], len(detections))
        log.log_event(
            "PLATEAU_CONFIRMED",
            "Wideband signal detected",
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
                freq=center_freq,
                score=result["score"]
            )
        else:
            log.log_event(
                "VIDEO_REJECTED",
                f"{classifier.name} rejected video",
                freq=center_freq,
                score=result["score"]
            )
    print("------------------------------")


# -----------------------------
# DEVICE SETUP
# -----------------------------

log = SDRLogger(sample_rate=SAMPLE_RATE)
# device = HackRFDevice(sample_rate=SAMPLE_RATE)
device = FileDevice(
    filepath="/home/liza/UCU/diploma/dataset/iq_recordings/002-rec.iq",
    sample_rate=SAMPLE_RATE
)
reader = SDRReader(device, buffer_size=BUFFER_SIZE, logger=log)
pl_detector = PlateauDetector(sample_rate=SAMPLE_RATE,
    fft_size=FFT_SIZE,
    wide_sampling_num=WIDE_SAMPLING_NUM,
    logger=log)

classifier = HarmonicClassifier(logger=log)

# classifier = CycloClassifier(sample_rate=SAMPLE_RATE,
#     fft_size=FFT_SIZE,
#     required_votes=DEMOD_REQUIRED_HITS,
#     logger=log)

# classifier = AutocorrClassifier(
#     sample_rate=SAMPLE_RATE,
#     decimation=10,
#     line_freq=15625,
#     threshold=0.1
# )

reader.start()

while True:
    fpv_detector()
