import SoapySDR
from SoapySDR import *
import numpy as np
import time

# -----------------------------
# PARAMETERS
# -----------------------------
CENTER_FREQ = 5840e6
SAMPLE_RATE = 20e6
GAIN = 35
FFT_SIZE = 8192
BUFFER_SIZE = 262144   # Large buffer prevents underruns
ALPHA = 0.2            # FFT averaging factor

EXPECTED_BW_MHZ = 8        # expected video width (6–8 MHz typical)
THRESHOLD_DB = 6           # bins must be 6 dB above noise floor
MIN_CLUSTER_MHZ = 2        # minimum cluster size to consider real

import numpy as np

def print_spectrum_bar(avg_power, bins=80):
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

# -----------------------------
# DEVICE SETUP
# -----------------------------
print("[INFO] Opening HackRF...")
sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, CENTER_FREQ)

sdr.setGain(SOAPY_SDR_RX, 0, False)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

buff = np.empty(BUFFER_SIZE, np.complex64)

avg_power = None

print("Monitoring 5840 MHz...")

# -----------------------------
# MAIN LOOP
# -----------------------------
while True:
    sr = sdr.readStream(rxStream, [buff], BUFFER_SIZE)

    if sr.ret <= 0:
        print("Stream error:", sr.ret)
        continue

    samples = buff[:sr.ret]

    # Detect zero buffers
    if np.all(samples == 0):
        print("⚠️ ZERO BUFFER DETECTED")
        continue

    # Use only FFT_SIZE samples for spectrum
    samples = samples[:FFT_SIZE]

    # Apply window
    window = np.hanning(len(samples))
    spectrum = np.fft.fftshift(np.fft.fft(samples * window))
    power = 20 * np.log10(np.abs(spectrum) + 1e-12)

    # Averaging like GQRX
    if avg_power is None:
        avg_power = power
    else:
        avg_power = ALPHA * power + (1 - ALPHA) * avg_power

    # Median + Peak
    median_power = np.median(avg_power)
    peak_index = np.argmax(avg_power)
    peak_power = avg_power[peak_index]

    # --------------------------------
    # THRESHOLD-BASED OCCUPANCY
    # --------------------------------

    freqs = np.linspace(
        CENTER_FREQ - SAMPLE_RATE/2,
        CENTER_FREQ + SAMPLE_RATE/2,
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
    else:
        print("No wideband signal detected")

    print("------------------------------")
    print_spectrum_bar(avg_power)