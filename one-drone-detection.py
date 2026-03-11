import SoapySDR
from SoapySDR import *
import numpy as np
import os
from datetime import datetime
import time

# -----------------------------
# PARAMETERS
# -----------------------------
MIN_FREQ = 1e2
MAX_FREQ = 6000e6
SAMPLE_RATE = 20e6
GAIN = 35
FFT_SIZE = 8192
BUFFER_SIZE = 262144   # Large buffer prevents underruns
ALPHA = 0.2            # FFT averaging factor

EXPECTED_BW_MHZ = 8        # expected video width (6–8 MHz typical)
THRESHOLD_DB = 6           # bins must be 6 dB above noise floor
MIN_CLUSTER_MHZ = 2        # minimum cluster size to consider real

WIDE_SAMPLING_NUM = 10

LOG_DIR = "logs"

avg_power = None
baseband_candidates = []

def fm_demod(iq):
    """
    Simple complex FM discriminator
    """
    return np.angle(iq[1:] * np.conj(iq[:-1]))

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

def classify_one_chunk(samples, hrf_center_freq):
    global avg_power

    window = np.hanning(len(samples))
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    power = 20 * np.log10(np.abs(spectrum) + 1e-12)

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

    noise_floor = np.median(avg_power)
    threshold = noise_floor + THRESHOLD_DB

    # Find bins above threshold
    active_bins = np.where(avg_power > threshold)[0]

    clusters = []
    if len(active_bins) > 0:
        current_cluster = [active_bins[0]]

        for i in range(1, len(active_bins)):
            if active_bins[i] == active_bins[i-1] + 1:
                current_cluster.append(active_bins[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [active_bins[i]]

        clusters.append(current_cluster)

    # Filter clusters by minimum bandwidth
    valid_clusters = []
    for cluster in clusters:
        bw_bins = cluster[-1] - cluster[0]
        bw_mhz = (bw_bins / FFT_SIZE) * SAMPLE_RATE / 1e6

        if bw_mhz >= MIN_CLUSTER_MHZ:
            valid_clusters.append((cluster, bw_mhz))

    if valid_clusters:
        largest_cluster, occupied_bw = max(valid_clusters, key=lambda x: x[1])
        center_bin = int(np.mean(largest_cluster))
        center_freq = freqs[center_bin] / 1e6
    else:
        occupied_bw = 0
        center_freq = 0

    print("\n------------------------------")
    print(f"Noise floor: {noise_floor:.1f} dB")
    print(f"Threshold:   {threshold:.1f} dB")

    if occupied_bw > 0:
        print(f"Detected signal bandwidth: {occupied_bw:.2f} MHz")
        print(f"Detected center frequency: {center_freq:.2f} MHz")
        
        # --------------------------------
        # FM DEMODULATION CHECK
        # --------------------------------

        demod = fm_demod(samples)

        # FFT of demodulated signal
        demod_fft = np.fft.fftshift(np.fft.fft(demod * np.hanning(len(demod))))
        demod_power = 20 * np.log10(np.abs(demod_fft) + 1e-12)

        demod_freqs = np.linspace(-SAMPLE_RATE/2, SAMPLE_RATE/2, len(demod))

        # Look around ±15 kHz
        sync_band = 2000  # ±2 kHz window
        target_freq = 15625  # PAL

        pos_mask = (demod_freqs > target_freq - sync_band) & (demod_freqs < target_freq + sync_band)
        neg_mask = (demod_freqs > -target_freq - sync_band) & (demod_freqs < -target_freq + sync_band)

        pos_energy = np.max(demod_power[pos_mask])
        neg_energy = np.max(demod_power[neg_mask])

        base_noise = np.median(demod_power)

        sync_detected = (pos_energy - base_noise > 6) and (neg_energy - base_noise > 6)

        print(f"FM sync +15kHz peak: {pos_energy:.1f} dB")
        print(f"FM sync -15kHz peak: {neg_energy:.1f} dB")

        if sync_detected:
            print(">>> ANALOG VIDEO SYNC DETECTED <<<")
        else:
            print("Wideband signal but no video sync")
    else:
        print("No wideband signal detected")

    print("------------------------------")
    print_spectrum_bar(avg_power, hrf_center_freq)

# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    current_freq = MIN_FREQ

    while current_freq < MAX_FREQ:
        sdr.setFrequency(SOAPY_SDR_RX, 0, current_freq)

        for i in range(WIDE_SAMPLING_NUM):
            sr = sdr.readStream(rxStream, [buff], BUFFER_SIZE)

            if sr.ret <= 0:
                print("Stream error:", sr.ret)
                return

            samples = buff[:sr.ret]

            # Detect zero buffers
            if np.all(samples == 0):
                print("⚠️ ZERO BUFFER DETECTED")
                return

            # Use only FFT_SIZE samples for spectrum
            samples = samples[:FFT_SIZE]
            classify_one_chunk(samples, current_freq)

        current_freq += SAMPLE_RATE


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

while True:
    main()