import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import threading
import time
import sys

FILE = "/home/liza/UCU/diploma/dataset/iq_recordings/sweep_20260407_184609002-rec.iq"

CENTER_FREQ = 5840e6
SAMPLE_RATE = 20e6
FFT_SIZE = 4096
ALPHA = 0.2

avg_power = None
latest_fft = None
lock = threading.Lock()

freqs = np.linspace(
    CENTER_FREQ - SAMPLE_RATE/2,
    CENTER_FREQ + SAMPLE_RATE/2,
    FFT_SIZE
) / 1e6

def read_iq_chunk(f, num_complex):
    raw = np.fromfile(f, dtype=np.int8, count=num_complex * 2)

    if len(raw) < num_complex * 2:
        return None

    raw = raw.astype(np.float32)

    iq = raw[0::2] + 1j * raw[1::2]
    iq /= 128.0

    return iq


def file_worker():
    global avg_power, latest_fft

    f = open(FILE, "rb")

    while True:
        samples = read_iq_chunk(f, FFT_SIZE)

        if samples is None:
            print("[INFO] Reached EOF, looping...")
            f.seek(0)
            avg_power = None
            continue

        window = np.hanning(len(samples))
        spectrum = np.fft.fftshift(np.fft.fft(samples * window))
        power = 20 * np.log10(np.abs(spectrum) + 1e-12)

        center = len(power) // 2
        power[center-5:center+5] = np.median(power)

        if avg_power is None:
            avg_power = power
        else:
            avg_power = ALPHA * power + (1 - ALPHA) * avg_power

        with lock:
            latest_fft = avg_power.copy()

        time.sleep(0.001)


thread = threading.Thread(target=file_worker, daemon=True)
thread.start()

app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(title="IQ File Spectrum Replay")
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