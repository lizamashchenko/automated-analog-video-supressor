import numpy as np
import matplotlib.pyplot as plt
import sys
from scipy.signal import spectrogram, butter, filtfilt

# -----------------------------------
# CONFIG
# -----------------------------------
SAMPLE_RATE = 20e6          # must match capture
DECIMATION = 100            # for LF spectrum
LPF_CUTOFF = 6e6            # optional low-pass cutoff (Hz)
FILTER_ORDER = 5
SYNC_FREQ = 15625           # Hz, PAL sync
SYNC_SEARCH_RANGE = (14000, 17000)  # Hz around sync for peak detection
ZOOM_BW = 20000             # Hz, ± zoom around sync for detailed plot

# -----------------------------------
# LOAD FILE
# -----------------------------------
if len(sys.argv) < 2:
    print("Usage: python visualize_demod.py demod_file.bin")
    sys.exit(1)

filename = sys.argv[1]
demod = np.fromfile(filename, dtype=np.float32)
print("Loaded samples:", len(demod))

# Remove DC
demod = demod - np.mean(demod)

# -----------------------------------
# LOW-PASS FILTER
# -----------------------------------
nyq = SAMPLE_RATE / 2
b, a = butter(FILTER_ORDER, LPF_CUTOFF / nyq, btype='low')
demod = filtfilt(b, a, demod)

# -----------------------------------
# DECIMATE FOR LF ANALYSIS
# -----------------------------------
demod_ds = demod[::DECIMATION]
fs_ds = SAMPLE_RATE / DECIMATION

# -----------------------------------
# LOW FREQUENCY SPECTRUM
# -----------------------------------
window = np.hanning(len(demod_ds))
fft = np.fft.fftshift(np.fft.fft(demod_ds * window))
power = 20 * np.log10(np.abs(fft) + 1e-12)
freqs = np.linspace(-fs_ds/2, fs_ds/2, len(demod_ds))

lf_mask = np.abs(freqs) < 50000  # ±50 kHz
plt.figure(figsize=(10,4))
plt.title("Low Frequency Spectrum (±50 kHz)")
plt.plot(freqs[lf_mask] / 1000, power[lf_mask])
plt.axvline(SYNC_FREQ/1000, color='r', linestyle='--', label='PAL Sync +')
plt.axvline(-SYNC_FREQ/1000, color='r', linestyle='--', label='PAL Sync -')
plt.xlabel("Frequency (kHz)")
plt.ylabel("Power (dB)")
plt.legend()
plt.tight_layout()

# -----------------------------------
# ZOOMED LF SPECTRUM AROUND SYNC
# -----------------------------------
zoom_mask = (freqs > -ZOOM_BW) & (freqs < ZOOM_BW)
plt.figure(figsize=(10,4))
plt.title("Zoomed Low Frequency Spectrum around Sync")
plt.plot(freqs[zoom_mask]/1000, power[zoom_mask])
plt.axvline(SYNC_FREQ/1000, color='r', linestyle='--', label='PAL Sync +')
plt.axvline(-SYNC_FREQ/1000, color='r', linestyle='--', label='PAL Sync -')
plt.xlabel("Frequency (kHz)")
plt.ylabel("Power (dB)")
plt.legend()
plt.tight_layout()

# -----------------------------------
# SYNC DETECTION
# -----------------------------------
search_mask = (
    (np.abs(freqs) > SYNC_SEARCH_RANGE[0]) &
    (np.abs(freqs) < SYNC_SEARCH_RANGE[1])
)

search_freqs = freqs[search_mask]
search_power = power[search_mask]

peak_index = np.argmax(search_power)
peak_freq = search_freqs[peak_index]
peak_power = search_power[peak_index]

noise_floor = np.median(power)
sync_strength = peak_power - noise_floor

print("\n--- SYNC ANALYSIS ---")
print(f"Peak frequency: {abs(peak_freq):.2f} Hz")
print(f"Peak strength above noise: {sync_strength:.2f} dB")

# -----------------------------------
# SPECTROGRAM
# -----------------------------------
f, t, Sxx = spectrogram(demod_ds, fs=fs_ds, nperseg=2048, noverlap=1024)
plt.figure(figsize=(10,5))
plt.title("Demod Spectrogram")
plt.pcolormesh(t, f/1000, 10*np.log10(Sxx + 1e-12), shading='gouraud')
plt.ylim(0, 50)  # show 0–50 kHz
plt.axhline(SYNC_FREQ/1000, color='r', linestyle='--', label='PAL Sync')
plt.xlabel("Time (s)")
plt.ylabel("Frequency (kHz)")
plt.colorbar(label="Power (dB)")
plt.tight_layout()
plt.show()