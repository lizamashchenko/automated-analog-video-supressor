import SoapySDR
from SoapySDR import *
import numpy as np
import time
import matplotlib.pyplot as plt


# --------------------
# Device setup
# --------------------
print("[INFO] Opening HackRF...")
sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, 20e6)
sdr.setGain(SOAPY_SDR_RX, 0, 32)

stream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(stream)

# --------------------
# Sweep config
# --------------------
f_start = 5e9
f_stop  = 6e9
step    = 10e6
fft_size = 4096

freqs = np.arange(f_start, f_stop, step)

# --------------------
# Plot setup
# --------------------
plt.ion()
fig, ax = plt.subplots()
line, = ax.plot(freqs/1e6, np.zeros(len(freqs)))

ax.set_xlabel("Frequency (MHz)")
ax.set_ylabel("Power (dB)")
ax.set_title("HackRF Wideband Sweep")
ax.set_ylim(-140, 0)
ax.grid(True)

plt.show()


buff = np.empty(fft_size, np.complex64)

print(f"[INFO] Sweep bins: {len(freqs)}")
print("[INFO] Starting sweep loop...\n")

# --------------------
# Sweep loop
# --------------------
sweep_id = 0

while True:
    sweep_id += 1
    powers = []

    t0 = time.time()

    for f in freqs:
        sdr.setFrequency(SOAPY_SDR_RX, 0, float(f))

        sr = sdr.readStream(
            stream,
            [buff],
            fft_size,
            timeoutUs=500000
        )

        if sr.ret > 0:
            # simple power estimate
            fft = np.fft.fftshift(np.fft.fft(buff))
            p = 20 * np.log10(np.mean(np.abs(fft)) + 1e-12)

            powers.append(p)
        else:
            powers.append(-200.0)

    t1 = time.time()

    powers = np.array(powers)

    # --------------------
    # Update plot
    # --------------------
    line.set_ydata(powers)
    ax.set_title(f"HackRF Wideband Sweep | Sweep {sweep_id} | {t1 - t0:.2f}s")
    fig.canvas.draw()
    fig.canvas.flush_events()

