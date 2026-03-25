import SoapySDR
from SoapySDR import *
import numpy as np
import os
from datetime import datetime
import time
from queue import Queue, Full, Empty
import threading

# TODO
# fix cluster width detection logic -> allow gaps DONE
# fix logging (log all events, basically move from console to a log file) DONE
# add threading as we are getting stuck at computationally heavy bits (2.4) DONE BUG FIX
# confidence over time DONE
# fix demodulation peak detection logic DONE

# add average from previous scans
# clean code FIX -> BROKE PLATEAU
# make an application
# introduce overlap
# adaptive thresholds 
# limit maximums, for jammer detection

# -----------------------------
# PARAMETERS
# -----------------------------

# Hack RF One setup
LNA_GAIN = 32
VGA_GAIN = 32
MIN_FREQ = 1000e6   # Hz
MAX_FREQ = 6000e6   # Hz
SAMPLE_RATE = 20e6  # Hz

# FFT params
FFT_SIZE = 4096
BUFFER_SIZE = 262144
FFT_SMOOTHING_FACTOR = 0.2

MHZ_PER_BIN = SAMPLE_RATE / FFT_SIZE / 1e6

# Plateu detector thresholds
ABOVE_NOISE_THRESHOLD = 3 # dB

# Coarse scan params
WIDE_SAMPLING_NUM = 10
EDGE_DROP_LEVEL = 2     # dB
MIN_LOBE_SIZE = 0.5     # dB
LOBE_MERGE_GAP = 2.0    # MHz

LOBE_MERGE_BINS = int(LOBE_MERGE_GAP / MHZ_PER_BIN)

PLATEU_REQUIRED_RATIO = 0.3
PLATEU_REQUIRED_HITS = int(WIDE_SAMPLING_NUM * PLATEU_REQUIRED_RATIO)

# Analogue video thresholds
MAX_VIDEO_WIDTH = 10    # MHz
MIN_VIDEO_WIDTH = 2.5   # MHz

# Demodulation thresholds
FREQ_TOLERANCE = 2e6  # Hz
MAX_SAMPLES_PER_PLATEAU = 5
DEMOD_REQUIRED_HITS = 3

# Logging
BASE_LOG_DIR = "logs"
RUN_ID = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
LOG_DIR = os.path.join(BASE_LOG_DIR, RUN_ID)

GENERAL_LOG = os.path.join(LOG_DIR, "events.log")
POSSIBLE_PLATEU_LOG = os.path.join(LOG_DIR, "possible_plateu.log")
CONFIRMED_PLATEU_LOG = os.path.join(LOG_DIR, "confirmed_plateu.log")
VIDEO_LOG = os.path.join(LOG_DIR, "video_detections.log")

# Data structures
class ScanState:
    def __init__(self):
        self.avg_power = None
        self.avg_power_map = {} 
        self.plateau_map = {}

# Globals
sample_queue = Queue(maxsize=100)
freq_lock = threading.Lock()

os.makedirs(LOG_DIR, exist_ok=True)

# Logging

def log_event(event_type, message, **kwargs):
    timestamp = datetime.utcnow().isoformat()

    extra = ",".join(f"{k}={v}" for k, v in kwargs.items())

    line = f"{timestamp},{event_type},{message}"
    if extra:
        line += "," + extra

    with open(GENERAL_LOG, "a") as f:
        f.write(line + "\n")

def log_possible_plateau(freq, bw, bin):
    with open(POSSIBLE_PLATEU_LOG, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{bw:.3f},{bin}\n")

def log_confirmed_plateau(freq, bw, hits):
    with open(CONFIRMED_PLATEU_LOG, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{bw:.3f},{hits}\n")

def log_video_detection(freq, pos_peak, neg_peak):
    with open(VIDEO_LOG, "a") as f:
        f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{pos_peak:.2f},{neg_peak:.2f}\n")

def print_spectrum_bar(avg_power, center_freq, bins=80):
    # Reduce avg_power to 'bins' points
    chunk_size = len(avg_power) // bins
    compressed = [np.mean(avg_power[i*chunk_size:(i+1)*chunk_size]) for i in range(bins)]

    # Normalize for display
    min_val, max_val = np.min(compressed), np.max(compressed)
    scaled = [(val - min_val) / (max_val - min_val + 1e-6) for val in compressed]

    # Map to 8 vertical levels
    bars = "▁▂▃▄▅▆▇█"
    line = "".join(bars[int(s*7)] for s in scaled)
    print(line)
    print(f"{(center_freq - SAMPLE_RATE/2) / 1e6} \t\t\t\t\t\t\t\t\t {(center_freq + SAMPLE_RATE/2) / 1e6}")

# Helpers
def get_freq_key(freq):
    return int(freq / SAMPLE_RATE) 

def get_samples():
    try:
        samples = sample_queue.get(timeout=0.1)
        if np.all(samples == 0):
            return None
        return samples[:FFT_SIZE]
    except:
        return None
    
def tune_hackrf(frequency):
    with freq_lock:
        sdr.setFrequency(SOAPY_SDR_RX, 0, frequency)

        while not sample_queue.empty():
            try:
                sample_queue.get_nowait()
            except:
                break

# Thread runners and future runners
# sdr_thread -> queue -> fpv_detector

def sdr_reader():
    global buff

    while True:
        sr = sdr.readStream(rxStream, [buff], BUFFER_SIZE)

        if sr.ret > 0:
            samples = buff[:sr.ret].copy()

            try:
                sample_queue.put(samples, timeout=0.01)
            except Full:
                try:
                    sample_queue.get_nowait()
                    sample_queue.put(samples, timeout=0.01)
                except:
                    pass
        else:
            print("Stream error:", sr.ret)
            log_event("STREAM_ERROR", "ReadStream failed", code=sr.ret)

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

        tune_hackrf(current_freq)

        # scan WIDE_SAMPLING_NUM times, to let SDR stabilize
        for _ in range(WIDE_SAMPLING_NUM):
            samples = get_samples()

            if samples is None:
                print("ZERO BUFFER DETECTED")
                log_event(
                    "ZERO_BUFFER",
                    "All samples are zero",
                    freq=current_freq
                )
                continue

            power = compute_power_spectrum(samples, state)    
            plateaus = detect_plateaus(power, current_freq)
            print_spectrum_bar(state.avg_power, current_freq)

            if plateaus:
                detections.append((samples, plateaus))

        plateau = validate_plateau(detections)

        if not plateau:
            if len(detections) > 0:
                log_event (
                        "PLATEAU_REJECTED",
                        "Not enough hits",
                        hits=len(detections),
                        required=PLATEU_REQUIRED_HITS,
                        freq=current_freq
                )
            current_freq += SAMPLE_RATE
            continue
        
        # log events
        log_confirmed_plateau(plateau["center_freq"], plateau["bandwidth"], len(detections))
        log_event(
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
        update_plateau_map(state, plateau)
        if state.avg_power is not None:
            state.avg_power_map[key] = state.avg_power.copy()
        current_freq += SAMPLE_RATE

    # proceed to demodulation check
    analyze_plateaus(state)
    print("------------------------------")

# Build spectrum
def compute_power_spectrum(samples, state):
    window = np.hanning(len(samples))
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    power = 20 * np.log10(np.abs(spectrum) + 1e-12)

    center = len(power) // 2
    power[center-5:center+5] = np.median(power)

    if state.avg_power is None:
        state.avg_power = power
    else:
        alpha = FFT_SMOOTHING_FACTOR
        state.avg_power = alpha * power + (1 - alpha) * state.avg_power

    return state.avg_power

# Detect plateau
# detect clusters -> build a plateau structure
def detect_plateaus(power, freq):
    freqs = np.linspace(
        freq - SAMPLE_RATE/2,
        freq + SAMPLE_RATE/2,
        FFT_SIZE
    )

    # smooth out and find clusters of strong signal
    clusters = find_clusters(power)

    return extract_plateau(clusters, freqs)


# Detect clusters
# find peaks -> expand into lobes -> merge into clusters of certain width (like analogue)
def find_clusters(power):
    smoothed = np.convolve(power, np.ones(3)/3, mode='same')
    noise_floor = np.median(smoothed)

    peak_indices = np.where(
        (smoothed[1:-1] > smoothed[:-2]) &
        (smoothed[1:-1] > smoothed[2:]) &
        (smoothed[1:-1] > noise_floor + ABOVE_NOISE_THRESHOLD)
    )[0] + 1

    lobes = expand_to_lobes(smoothed, peak_indices, noise_floor)
    clusters = merge_lobes(lobes)

    # debug print
    print("\n------------------------------")
    print(f"Noise floor: {noise_floor:.1f} dB")
    print(f"Peaks found: {len(peak_indices)}")
    print(f"Lobes: {len(lobes)}")
    print(f"Merged clusters: {len(clusters)}")

    return clusters

def expand_to_lobes(data, peaks, noise):
    edge_threshold = noise + EDGE_DROP_LEVEL
    lobes = []

    for peak_idx in peaks:
        left = peak_idx
        while left > 0 and data[left] > edge_threshold:
            left -= 1

        right = peak_idx
        while right < len(data)-1 and data[right] > edge_threshold:
            right += 1

        # filter out sharp peaks
        bw_bins = right - left + 1
        bw_mhz = bw_bins * MHZ_PER_BIN

        if bw_mhz >= MIN_LOBE_SIZE:
            lobes.append((left, right))

    return lobes

def merge_lobes(lobes):
    clusters = []

    if not lobes:
        return clusters
    
    lobes.sort()
    cur_left, cur_right = lobes[0]

    for left, right in lobes[1:]:
        if left - cur_right <= LOBE_MERGE_BINS:
            cur_right = max(cur_right, right)
        else:
            cur_left, cur_right = left, right
            bw_bins = cur_right - cur_left + 1
            bw_mhz = bw_bins * MHZ_PER_BIN

            if bw_mhz >= MIN_VIDEO_WIDTH:
                clusters.append((cur_left, cur_right, bw_mhz))

    bw_bins = cur_right - cur_left + 1
    bw_mhz = bw_bins * MHZ_PER_BIN

    if bw_mhz >= MIN_VIDEO_WIDTH:
        clusters.append((cur_left, cur_right, bw_mhz))

    return clusters

# structurize data to a simple format
def extract_plateau(clusters, freqs):
    if not clusters:
        return None

    left, right, bw = max(clusters, key=lambda x: x[2])
    center_bin = (left + right) // 2

    return {
        "center_freq": freqs[center_bin],
        "bandwidth": bw,
        "bin": center_bin
    }

def validate_plateau(detections):
    if len(detections) < PLATEU_REQUIRED_HITS:
        return None

    freqs = [d[1]["center_freq"] for d in detections]
    bws = [d[1]["bandwidth"] for d in detections]

    return {
        "center_freq": np.median(freqs),
        "bandwidth": np.max(bws),
        "samples": [d[0] for d in detections]
    }

def update_plateau_map(state, plateau):
    key = int(plateau["center_freq"] / FREQ_TOLERANCE)

    if key not in state.plateau_map:
        state.plateau_map[key] = []

    state.plateau_map[key].extend(plateau["samples"])
    state.plateau_map[key] = state.plateau_map[key][-5:]

    
# Demodulate and fit to NTSC/PAL video

def analyze_plateaus(state):
    for key, samples_list in state.plateau_map.items():

        if len(samples_list) < MAX_SAMPLES_PER_PLATEAU:
            continue

        votes = 0
        center_freq = key * FREQ_TOLERANCE

        for samples in samples_list:
            samples = samples[:FFT_SIZE]

            demod = fm_demod(samples)
            demod_fft = np.fft.fftshift(np.fft.fft(demod * np.hanning(len(demod))))
            demod_power = 20 * np.log10(np.abs(demod_fft) + 1e-12)
            demod_freqs = np.linspace(-SAMPLE_RATE/2, SAMPLE_RATE/2, len(demod))

            base_noise = np.median(demod_power)
            target_freq = 15625
            sync_band = 2000

            harmonics = [1, 2, 3, 4]
            harmonic_hits = 0

            for h in harmonics:
                f = h * target_freq

                mask = (np.abs(demod_freqs - f) < sync_band) | \
                       (np.abs(demod_freqs + f) < sync_band)

                if np.mean(demod_power[mask]) - base_noise > 5:
                    harmonic_hits += 1

            if harmonic_hits >= 3:
                votes += 1

        print(f"[{center_freq/1e6:.1f} MHz] Votes: {votes}")

        if votes >= DEMOD_REQUIRED_HITS:
            print("ANALOG VIDEO CONFIRMED")

            log_video_detection(center_freq, votes, len(samples_list))
            log_event(
                "VIDEO_CONFIRMED",
                "Analog video detected",
                freq=center_freq,
                votes=votes
            )

def fm_demod(iq):
    return np.angle(iq[1:] * np.conj(iq[:-1]))

# -----------------------------
# DEVICE SETUP
# -----------------------------
print("[INFO] Opening HackRF...")
sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)

sdr.setGain(SOAPY_SDR_RX, 0, False)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

buff = np.empty(BUFFER_SIZE, np.complex64)

reader_thread = threading.Thread(target=sdr_reader, daemon=True)
reader_thread.start()

while True:
    fpv_detector()
