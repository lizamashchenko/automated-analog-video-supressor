import SoapySDR
from SoapySDR import *
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import sys
import threading
import time
import os
from datetime import datetime

demod_buffer = []
log_counter = 0

history = []
HISTORY_LEN = 8
HISTORY_THRESHOLD = 5
CENTER_FREQ = 5840e6

SAMPLE_RATE = 20e6
FFT_SIZE = 4096
BUFFER_SIZE = 65536
ALPHA = 0.2

MIN_CLUSTER_MHZ = 2.5

EDGE_DROP_DB = 2
PEAK_THRESHOLD_DB = 3
MIN_LOBE_MHZ = 0.5
MERGE_GAP_MHZ = 2.0

BIN_TO_MHZ = SAMPLE_RATE / FFT_SIZE / 1e6
MERGE_GAP_BINS = int(MERGE_GAP_MHZ / BIN_TO_MHZ)

LOG_DIR = "demod_logs"
os.makedirs(LOG_DIR, exist_ok=True)

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

iq_file = os.path.join(LOG_DIR, f"iq_{timestamp}.bin")
demod_file = os.path.join(LOG_DIR, f"demod_{timestamp}.bin")
fft_file = os.path.join(LOG_DIR, f"fft_{timestamp}.bin")
meta_file = os.path.join(LOG_DIR, f"meta_{timestamp}.txt")

print("[INFO] Opening HackRF...")
sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setFrequency(SOAPY_SDR_RX, 0, CENTER_FREQ)
sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 40)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 32)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

time.sleep(0.1)

buff = np.empty(BUFFER_SIZE, np.complex64)

avg_power = None
latest_fft = None
lock = threading.Lock()

freqs = np.linspace(
    CENTER_FREQ - SAMPLE_RATE/2,
    CENTER_FREQ + SAMPLE_RATE/2,
    FFT_SIZE
) / 1e6

def fm_demod(iq):
    return np.angle(iq[1:] * np.conj(iq[:-1]))

def band_energy(power, freqs, center, width):
                mask = (freqs > center - width) & (freqs < center + width)
                if np.any(mask):
                    return np.mean(power[mask])
                return -200

def save_capture(demod, demod_freqs, demod_power, metadata):
    global log_counter

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    base = f"{LOG_DIR}/capture_{timestamp}"

    np.array(demod, dtype=np.float32).tofile(base + "_demod.bin")
    np.array(demod_freqs, dtype=np.float32).tofile(base + "_freqs.bin")
    np.array(demod_power, dtype=np.float32).tofile(base + "_spectrum.bin")
    with open(base + "_meta.txt", "w") as f:
        for k, v in metadata.items():
            f.write(f"{k}: {v}\n")

    log_counter += 1
    print(f"[LOG] Saved capture {log_counter} -> {base}")

def sdr_worker():
    global avg_power, latest_fft

    while True:
        sr = sdr.readStream(rxStream, [buff], BUFFER_SIZE)

        if sr.ret <= 0 or sr.ret < FFT_SIZE:
            continue

        samples = buff[:FFT_SIZE]

        window = np.hanning(len(samples))
        spectrum = np.fft.fftshift(np.fft.fft(samples * window))
        power = 20 * np.log10(np.abs(spectrum) + 1e-12)

        center = len(power) // 2
        power[center-5:center+5] = np.median(power)

        if avg_power is None:
            avg_power = power
        else:
            avg_power = ALPHA * power + (1 - ALPHA) * avg_power

        smoothed = np.convolve(avg_power, np.ones(3)/3, mode='same')

        noise_floor = np.median(smoothed)

        peak_indices = np.where(
            (smoothed[1:-1] > smoothed[:-2]) &
            (smoothed[1:-1] > smoothed[2:]) &
            (smoothed[1:-1] > noise_floor + PEAK_THRESHOLD_DB)
        )[0] + 1

        clusters = []
        edge_threshold = noise_floor + EDGE_DROP_DB

        for peak_idx in peak_indices:
            left = peak_idx
            while left > 0 and smoothed[left] > edge_threshold:
                left -= 1

            right = peak_idx
            while right < len(smoothed)-1 and smoothed[right] > edge_threshold:
                right += 1

            clusters.append((left, right))

        filtered = []
        for left, right in clusters:
            bw_bins = right - left + 1
            bw_mhz = bw_bins * BIN_TO_MHZ

            if bw_mhz >= MIN_LOBE_MHZ:
                filtered.append((left, right))

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

        print("\n------------------------------")
        print(f"Noise floor: {noise_floor:.1f} dB")
        print(f"Peaks found: {len(peak_indices)}")
        print(f"Lobes: {len(filtered)}")
        print(f"Merged clusters: {len(merged)}")

        if occupied_bw > 0:
            print(f"Detected BW: {occupied_bw:.2f} MHz")
            print(f"Center freq: {center_freq:.2f} MHz")

            detected_center_hz = center_freq * 1e6
            freq_offset = detected_center_hz - CENTER_FREQ

            n = np.arange(len(samples))
            mixer = np.exp(-1j * 2 * np.pi * freq_offset * n / SAMPLE_RATE)
            shifted = samples * mixer

            spec = np.fft.fftshift(np.fft.fft(shifted))
            freq_axis = np.linspace(-SAMPLE_RATE/2, SAMPLE_RATE/2, len(spec))

            mask = np.abs(freq_axis) <= 5e6
            spec_filtered = spec * mask

            filtered = np.fft.ifft(np.fft.ifftshift(spec_filtered))

            demod = fm_demod(filtered)

            demod_fft = np.fft.fftshift(np.fft.fft(demod * np.hanning(len(demod))))
            demod_power = 20 * np.log10(np.abs(demod_fft) + 1e-12)

            demod_freqs = np.linspace(-SAMPLE_RATE/2, SAMPLE_RATE/2, len(demod))

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
                    pos_energy = np.mean(demod_power[mask_pos])
                    neg_energy = np.mean(demod_power[mask_neg])

                    if (pos_energy - base_noise > 5) and (neg_energy - base_noise > 5):
                        harmonic_hits += 1

            main_mask = (np.abs(demod_freqs) > target_freq - sync_band) & \
                        (np.abs(demod_freqs) < target_freq + sync_band)

            main_energy = np.mean(demod_power[main_mask])

            exclude_mask = (np.abs(demod_freqs) < 2000) | main_mask
            rest_energy = np.mean(demod_power[~exclude_mask])

            dominance = main_energy - rest_energy

            sync_detected = (harmonic_hits >= 3) and (dominance > 10)
            history.append(1 if sync_detected else 0)

            if len(history) > HISTORY_LEN:
                history.pop(0)

            confidence = sum(history)
            confirmed = confidence >= HISTORY_THRESHOLD

            print(f"Harmonics detected: {harmonic_hits}/4")
            print(f"Peak dominance: {dominance:.2f} dB")

            with open(demod_file, "ab") as f:
                demod.astype(np.float32).tofile(f)

            with open(meta_file, "a") as f:
                f.write(
                    f"BW={occupied_bw:.3f}MHz "
                    f"Center={center_freq:.3f}MHz "
                    f"Noise={noise_floor:.2f}dB"
                    f"Peak dominance: {dominance:.2f} dB"
                    f"Harmonics det: {harmonic_hits}/4 \n"
                )

            print(f"FM sync +15kHz peak: {pos_energy:.1f} dB")
            print(f"FM sync -15kHz peak: {neg_energy:.1f} dB")

            print(f"History: {history} ({confidence}/{HISTORY_LEN})")

            if confirmed:
                print("ANALOG VIDEO CONFIRMED")
            elif sync_detected:
                print("Possible video (not stable yet)")
            else:
                print("Wideband signal but no video sync")
                        
        else:
            print("No wideband signal detected")

        print("------------------------------")

        with lock:
            latest_fft = avg_power.copy()

thread = threading.Thread(target=sdr_worker, daemon=True)
thread.start()

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