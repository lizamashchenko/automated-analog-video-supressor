import SoapySDR
from SoapySDR import *
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import threading
import queue
import sys
import time

# -----------------------------
# CONFIG
# -----------------------------
SAMPLE_RATE = 10e6
FFT_SIZE = 4096

START_FREQ = 1e9
STOP_FREQ = 6e9
STEP = SAMPLE_RATE * 0.6

# generate sweep frequencies
freq_list = np.arange(START_FREQ, STOP_FREQ, STEP)

# -----------------------------
# SDR INIT
# -----------------------------
sdr = SoapySDR.Device(dict(driver="hackrf"))

sdr.setSampleRate(SOAPY_SDR_RX, 0, SAMPLE_RATE)
sdr.setBandwidth(SOAPY_SDR_RX, 0, SAMPLE_RATE)

sdr.setGain(SOAPY_SDR_RX, 0, "LNA", 32)
sdr.setGain(SOAPY_SDR_RX, 0, "VGA", 24)

rxStream = sdr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
sdr.activateStream(rxStream)

time.sleep(0.2)

# -----------------------------
# QUEUE
# -----------------------------
q = queue.Queue(maxsize=100)

# -----------------------------
# SDR THREAD (SCANNER)
# -----------------------------
def sdr_worker():
    buff = np.zeros(FFT_SIZE, dtype=np.complex64)
    window = np.hanning(FFT_SIZE)

    while True:
        for f in freq_list:
            sdr.setFrequency(SOAPY_SDR_RX, 0, f)

            time.sleep(0.002)  # allow LO settle

            sr = sdr.readStream(rxStream, [buff], FFT_SIZE, timeoutUs=100000)

            if sr.ret > 0:
                samples = buff.copy()

                # DC removal
                samples -= np.mean(samples)

                samples *= window

                fft = np.fft.fftshift(np.fft.fft(samples))
                power = 10 * np.log10((np.abs(fft) ** 2) / FFT_SIZE + 1e-12)

                # frequency axis for this chunk
                freqs = np.fft.fftshift(np.fft.fftfreq(FFT_SIZE, 1 / SAMPLE_RATE))
                freqs = freqs + f

                try:
                    q.put_nowait((freqs, power))
                except queue.Full:
                    q.get_nowait()
                    q.put_nowait((freqs, power))

threading.Thread(target=sdr_worker, daemon=True).start()

# -----------------------------
# GUI
# -----------------------------
app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(title="Wideband Scanner")
plot = win.addPlot(title="Spectrum")
curve = plot.plot(pen='y')

plot.setLabel('left', 'Power', 'dB')
plot.setLabel('bottom', 'Frequency', 'GHz')

plot.setYRange(-100, -30)

win.show()

# -----------------------------
# STITCH BUFFER
# -----------------------------
# global frequency grid
global_freqs = np.linspace(START_FREQ, STOP_FREQ, 20000)
global_power = np.ones_like(global_freqs) * -120

# -----------------------------
# UPDATE LOOP
# -----------------------------
def update():
    global global_power

    updated = False

    while not q.empty():
        freqs, power = q.get()

        # interpolate chunk onto global grid
        interp = np.interp(global_freqs, freqs, power)

        # max-hold (important for scanning)
        global_power = np.maximum(global_power, interp)

        updated = True

    if updated:
        curve.setData(global_freqs / 1e9, global_power)

timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(50)

sys.exit(app.exec())