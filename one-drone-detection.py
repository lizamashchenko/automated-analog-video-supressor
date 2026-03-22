import SoapySDR
from SoapySDR import *
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import sys
import threading
import time

# -----------------------------
# PARAMETERS
# -----------------------------
CENTER_FREQ = 5840e6
SAMPLE_RATE = 20e6
FFT_SIZE = 8192
BUFFER_SIZE = 65536
ALPHA = 0.2

MIN_CLUSTER_MHZ = 2.5

EDGE_DROP_DB = 2        # how far from peak to expand
PEAK_THRESHOLD_DB = 3   # above noise to consider peak
MIN_LOBE_MHZ = 0.5      # minimum lobe size
MERGE_GAP_MHZ = 2.0     # max gap to merge lobes

# -----------------------------
# SDR SETUP
# -----------------------------
print("[INFO] Opening HackRF...")
sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, CENTER_FREQ)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

time.sleep(0.1)

buff = np.empty(BUFFER_SIZE, np.complex64)

avg_power = None
latest_fft = None
lock = threading.Lock()

# Frequency axis (MHz)
freqs = np.linspace(
    CENTER_FREQ - SAMPLE_RATE/2,
    CENTER_FREQ + SAMPLE_RATE/2,
    FFT_SIZE
) / 1e6

# Precompute bin conversion
BIN_TO_MHZ = SAMPLE_RATE / FFT_SIZE / 1e6
MERGE_GAP_BINS = int(MERGE_GAP_MHZ / BIN_TO_MHZ)

# -----------------------------
# SDR THREAD
# -----------------------------
def sdr_worker():
    global avg_power, latest_fft

    while True:
        sr = sdr.readStream(rxStream, [buff], BUFFER_SIZE)

        if sr.ret <= 0 or sr.ret < FFT_SIZE:
            continue

        samples = buff[:FFT_SIZE]

        # FFT
        window = np.hanning(len(samples))
        spectrum = np.fft.fftshift(np.fft.fft(samples * window))
        power = 20 * np.log10(np.abs(spectrum) + 1e-12)

        # Remove DC spike
        center = len(power) // 2
        power[center-5:center+5] = np.median(power)

        # Averaging
        if avg_power is None:
            avg_power = power
        else:
            avg_power = ALPHA * power + (1 - ALPHA) * avg_power

        smoothed = np.convolve(avg_power, np.ones(3)/3, mode='same')

        # -----------------------------
        # DETECTION PIPELINE
        # -----------------------------
        noise_floor = np.median(smoothed)

        # ---- 1. Find peaks ----
        peak_indices = np.where(
            (smoothed[1:-1] > smoothed[:-2]) &
            (smoothed[1:-1] > smoothed[2:]) &
            (smoothed[1:-1] > noise_floor + PEAK_THRESHOLD_DB)
        )[0] + 1

        clusters = []
        edge_threshold = noise_floor + EDGE_DROP_DB

        # ---- 2. Expand peaks ----
        for peak_idx in peak_indices:
            left = peak_idx
            while left > 0 and smoothed[left] > edge_threshold:
                left -= 1

            right = peak_idx
            while right < len(smoothed)-1 and smoothed[right] > edge_threshold:
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

        if valid_clusters:
            left, right, occupied_bw = max(valid_clusters, key=lambda x: x[2])
            center_bin = (left + right) // 2
            center_freq = freqs[center_bin]
        else:
            occupied_bw = 0
            center_freq = 0

        # ---- DEBUG ----
        print("\n------------------------------")
        print(f"Noise floor: {noise_floor:.1f} dB")
        print(f"Peaks found: {len(peak_indices)}")
        print(f"Lobes: {len(filtered)}")
        print(f"Merged clusters: {len(merged)}")

        if occupied_bw > 0:
            print(f"Detected BW: {occupied_bw:.2f} MHz")
            print(f"Center freq: {center_freq:.2f} MHz")
        else:
            print("No wideband signal detected")
        print("------------------------------")

        # Share FFT
        with lock:
            latest_fft = avg_power.copy()

        # time.sleep(0.001)

# Start SDR thread
thread = threading.Thread(target=sdr_worker, daemon=True)
thread.start()

# -----------------------------
# GUI
# -----------------------------
app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(title="Analog Video Detector")
plot = win.addPlot(title="Live Spectrum")
curve = plot.plot(pen='y')

plot.setLabel('left', 'Power', 'dB')
plot.setLabel('bottom', 'Frequency', 'MHz')
plot.setYRange(-100, 0)

win.show()

def update():
    global latest_fft

    with lock:
        if latest_fft is None:
            return
        data = latest_fft.copy()

    curve.setData(freqs, data)

timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(50)

sys.exit(app.exec())