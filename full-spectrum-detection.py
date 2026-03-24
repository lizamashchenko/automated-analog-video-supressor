import SoapySDR
from SoapySDR import *
import numpy as np
import os
from datetime import datetime
import time
from queue import Queue, Full, Empty
import threading

sample_queue = Queue(maxsize=100)
freq_lock = threading.Lock()

# TODO
# fix cluster width detection logic -> allow gaps DONE
# fix logging (log all events, basically move from console to a log file) DONE
# add threading as we are getting stuck at computationally heavy bits (2.4) DONE BUG FIX
# confidence over time DONE

# fix demodulation peak detection logic
# add average from previous scans
# clean code
# make an application
# introduce overlap
# adaptive thresholds 

# -----------------------------
# PARAMETERS
# -----------------------------
MIN_FREQ = 1000e6
MAX_FREQ = 6000e6
SAMPLE_RATE = 20e6
FFT_SIZE = 4096
BUFFER_SIZE = 262144 # Large buffer prevents underruns
ALPHA = 0.2 # FFT averaging factor

EXPECTED_BW_MHZ = 8 # expected video width (6–8 MHz typical)
THRESHOLD_DB = 3 # bins must be 6 dB above noise floor
MIN_CLUSTER_MHZ = 2.5 # minimum cluster size to consider real
MAX_CLUSTER_MHZ = 10

WIDE_SAMPLING_NUM = 10

BASE_LOG_DIR = "logs"

RUN_ID = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
LOG_DIR = os.path.join(BASE_LOG_DIR, RUN_ID)

EDGE_DROP_DB = 2        # how far from peak to expand
PEAK_THRESHOLD_DB = 4   # above noise to consider peak
MIN_LOBE_MHZ = 0.5      # minimum lobe size
MERGE_GAP_MHZ = 2.0     # max gap to merge lobes

# Precompute bin conversion
BIN_TO_MHZ = SAMPLE_RATE / FFT_SIZE / 1e6
MERGE_GAP_BINS = int(MERGE_GAP_MHZ / BIN_TO_MHZ)

REQUIRED_RATIO = 0.3
REQUIRED_HITS = int(WIDE_SAMPLING_NUM * REQUIRED_RATIO)

MAX_ERRORS = 5 

avg_power = None
baseband_candidates = []

video_history = {}

HISTORY_LEN = 6
HISTORY_THRESHOLD = 4

FREQ_TOLERANCE = 2e6  # 2 MHz bucket

# -----------------------------
# LOGGING
# -----------------------------
os.makedirs(LOG_DIR, exist_ok=True)

GENERAL_LOG = os.path.join(LOG_DIR, "events.log")
POSSIBLE_PLATEU_LOG = os.path.join(LOG_DIR, "possible_plateu.log")
CONFIRMED_PLATEU_LOG = os.path.join(LOG_DIR, "confirmed_plateu.log")
VIDEO_LOG = os.path.join(LOG_DIR, "video_detections.log")


def log_event(event_type, message, **kwargs):
    """
    General structured logger
    """
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

def reset_stream():
    global rxStream
    try:
        sdr.deactivateStream(rxStream)
        sdr.closeStream(rxStream)
    except:
        pass

    rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
    sdr.activateStream(rxStream)

def fm_demod(iq):
    """
    Simple complex FM discriminator
    """
    return np.angle(iq[1:] * np.conj(iq[:-1]))

def get_freq_key(freq):
    return int(freq / FREQ_TOLERANCE)

def print_spectrum_bar(avg_power, center_freq, bins=80):
    """
    Prints a simple ASCII spectrum to console.
    avg_power: array of power readings (dB or linear)
    bins: number of horizontal columns in the console
    """
    # Reduce avg_power to 'bins' points
    chunk_size = len(avg_power) // bins
    compressed = [np.mean(avg_power[i*chunk_size:(i+1)*chunk_size]) for i in range(bins)]

    # Normalize for display
    min_val, max_val = np.min(compressed), np.max(compressed)
    scaled = [(val - min_val) / (max_val - min_val + 1e-6) for val in compressed]

    # Map to 8 vertical levels ░ ▒ ▓ █
    bars = "▁▂▃▄▅▆▇█"
    line = "".join(bars[int(s*7)] for s in scaled)
    print(line)
    print(f"{(center_freq - SAMPLE_RATE/2) / 1e6} \t\t\t\t\t\t\t\t\t {(center_freq + SAMPLE_RATE/2) / 1e6}")

def detect_clusters(data, noise_level):
    # ---- 1. Find peaks ----
    peak_indices = np.where(
        (data[1:-1] > data[:-2]) &
        (data[1:-1] > data[2:]) &
        (data[1:-1] > noise_level + PEAK_THRESHOLD_DB)
    )[0] + 1

    clusters = []
    edge_threshold = noise_level + EDGE_DROP_DB

    # ---- 2. Expand peaks ----
    for peak_idx in peak_indices:
        left = peak_idx
        while left > 0 and data[left] > edge_threshold:
            left -= 1

        right = peak_idx
        while right < len(data)-1 and data[right] > edge_threshold:
            right += 1

        clusters.append((left, right))

    # ---- 3. Filter small lobes ----
    filtered = []
    for left, right in clusters:
        bw_bins = right - left + 1
        bw_mhz = bw_bins * BIN_TO_MHZ

        if bw_mhz >= MIN_LOBE_MHZ:
            filtered.append((left, right))

    # ---- 4. Merge nearby lobes ----
    merged = []
    if filtered:
        filtered.sort()
        cur_left, cur_right = filtered[0]

        for left, right in filtered[1:]:
            if left - cur_right <= MERGE_GAP_BINS:
                cur_right = max(cur_right, right)
            else:
                merged.append((cur_left, cur_right))
                cur_left, cur_right = left, right

        merged.append((cur_left, cur_right))

    # ---- 5. Final selection ----
    valid_clusters = []
    for left, right in merged:
        bw_bins = right - left + 1
        bw_mhz = bw_bins * BIN_TO_MHZ

        if bw_mhz >= MIN_CLUSTER_MHZ:
            valid_clusters.append((left, right, bw_mhz))

    print("\n------------------------------")
    print(f"Noise floor: {noise_level:.1f} dB")
    print(f"Peaks found: {len(peak_indices)}")
    print(f"Lobes: {len(filtered)}")
    print(f"Merged clusters: {len(merged)}")

    return valid_clusters

def detect_plateus(samples, hrf_center_freq):
    global avg_power

    window = np.hanning(len(samples))
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    power = 20 * np.log10(np.abs(spectrum) + 1e-12)

    center = len(power) // 2
    power[center-5:center+5] = np.median(power)

    # Averaging like GQRX
    if avg_power is None:
        avg_power = power
    else:
        avg_power = ALPHA * power + (1 - ALPHA) * avg_power

    # --------------------------------
    # THRESHOLD-BASED OCCUPANCY
    # --------------------------------

    freqs = np.linspace(
        hrf_center_freq - SAMPLE_RATE/2,
        hrf_center_freq + SAMPLE_RATE/2,
        FFT_SIZE
    )

    smoothed = np.convolve(avg_power, np.ones(3)/3, mode='same')
    noise_floor = np.median(smoothed)

    valid_clusters = detect_clusters(smoothed, noise_floor)
   
    if valid_clusters:
        left, right, occupied_bw = max(valid_clusters, key=lambda x: x[2])
        center_bin = (left + right) // 2
        center_freq = freqs[center_bin]
        
        log_possible_plateau(center_freq, occupied_bw, center_bin)
        log_event(
            "POSSIBLE_PLATEAU_HIT",
            "Detected candidate",
            freq=center_freq,
            bw=occupied_bw,
            bin=center_bin
        )

        return occupied_bw, center_freq
    
    else:
        return 0, 0
    
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
            
# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    global avg_power
    current_freq = MIN_FREQ
    demod_data = []
    plateau_map = {}
    MAX_SAMPLES_PER_PLATEAU = 5
    REQUIRED_VOTES = 3
    FREQ_TOLERANCE = 2e6

    # coarse plateu scan
    while current_freq < MAX_FREQ:
        with freq_lock:
            sdr.setFrequency(SOAPY_SDR_RX, 0, current_freq)
            while not sample_queue.empty():
                try:
                    sample_queue.get_nowait()
                except:
                    break

        avg_power = None
        detections = []

        for i in range(WIDE_SAMPLING_NUM):
            try:
                samples = sample_queue.get(timeout=0.1)
            except:
                i -= 1
                continue

            if np.all(samples == 0):
                print("⚠️ ZERO BUFFER DETECTED")
                log_event(
                    "ZERO_BUFFER",
                    "All samples are zero",
                    freq=current_freq
                )
                i -= 1
                continue

            samples = samples[:FFT_SIZE]
            res_width, res_center = detect_plateus(samples, current_freq)
            
            print_spectrum_bar(avg_power, current_freq)

            if res_width != 0:
                detections.append((samples, res_width, res_center))


        if len(detections) < REQUIRED_HITS:
            current_freq += SAMPLE_RATE

            if (len(detections) != 0):
                log_event(
                    "PLATEAU_REJECTED",
                    "Not enough hits",
                    hits=len(detections),
                    required=REQUIRED_HITS,
                    freq=current_freq
                )
            continue

        # means we found a plateu
        # should store in the map, last 5 of the samples from the loop above

        samples_list = [d[0] for d in detections]
        bw_list = [d[1] for d in detections]
        freq_list = [d[2] for d in detections]

        center_freq = np.median(freq_list)
        occupied_bw = np.max(bw_list)

        key = int(center_freq / FREQ_TOLERANCE)

        if key not in plateau_map:
            plateau_map[key] = []

        for s in samples_list:
            plateau_map[key].append(s)

        # keep only last 5
        plateau_map[key] = plateau_map[key][-MAX_SAMPLES_PER_PLATEAU:]

        log_confirmed_plateau(center_freq, occupied_bw, len(detections))
        log_event(
            "PLATEAU_CONFIRMED",
            "Wideband signal detected",
            freq=center_freq,
            bw=occupied_bw,
            hits=len(detections)
        )
        current_freq += SAMPLE_RATE
        
        print(f"Detected signal bandwidth: {occupied_bw:.2f} MHz")
        print(f"Detected center frequency: {center_freq:.2f} MHz")
        print(f"Number of hits: {len(detections):.2f} MHz")

    # Demodulation check for each platue we detected. we have 5 samples, at least 3/5 should return true on demod check
    print("\n==== DEMOD CHECK ====")

    for key, samples_list in plateau_map.items():

        if len(samples_list) < MAX_SAMPLES_PER_PLATEAU:
            continue

        votes = 0

        # approximate center freq from key
        center_freq = key * FREQ_TOLERANCE

        for samples in samples_list:

            samples = samples[:FFT_SIZE]

            # ---- DEMOD ----
            demod = fm_demod(samples)

            demod_fft = np.fft.fftshift(np.fft.fft(demod * np.hanning(len(demod))))
            demod_power = 20 * np.log10(np.abs(demod_fft) + 1e-12)

            demod_freqs = np.linspace(-SAMPLE_RATE/2, SAMPLE_RATE/2, len(demod))

            # ---- YOUR DETECTION ----
            sync_band = 2000
            target_freq = 15625
            base_noise = np.median(demod_power)

            harmonics = [1, 2, 3, 4]
            harmonic_hits = 0

            for h in harmonics:
                f = h * target_freq

                mask_pos = (demod_freqs > f - sync_band) & (demod_freqs < f + sync_band)
                mask_neg = (demod_freqs > -f - sync_band) & (demod_freqs < -f + sync_band)

                if np.any(mask_pos) and np.any(mask_neg):
                    pos_e = np.mean(demod_power[mask_pos])
                    neg_e = np.mean(demod_power[mask_neg])

                    if (pos_e - base_noise > 5) and (neg_e - base_noise > 5):
                        harmonic_hits += 1

            main_mask = (np.abs(demod_freqs) > target_freq - sync_band) & \
                        (np.abs(demod_freqs) < target_freq + sync_band)

            main_energy = np.mean(demod_power[main_mask])

            exclude_mask = (np.abs(demod_freqs) < 2000) | main_mask
            rest_energy = np.mean(demod_power[~exclude_mask])

            dominance = main_energy - rest_energy

            if (harmonic_hits >= 3) and (dominance > 10):
                votes += 1

        print(f"[{center_freq/1e6:.1f} MHz] Votes: {votes}/{len(samples_list)}")

        if votes >= REQUIRED_VOTES:
            print("ANALOG VIDEO CONFIRMED")

            log_video_detection(center_freq, votes, len(samples_list))
            log_event(
                "VIDEO_CONFIRMED",
                "Analog video detected",
                freq=center_freq,
                votes=votes
            )

        else:
            print("Rejected")
    else:
        print("No wideband signal detected")

    print("------------------------------")

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

print("Monitoring 5840 MHz...")
reader_thread = threading.Thread(target=sdr_reader, daemon=True)
reader_thread.start()

while True:
    main()
