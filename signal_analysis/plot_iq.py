import argparse
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import threading
import time
import sys


# usage: plot_iq.py [-h] --file PATH [--center-freq HZ] [--sample-rate HZ] [--fft-size N] [--alpha A]

# Replay an IQ file as a live spectrum plot

# options:
#   -h, --help        show this help message and exit
#   --file PATH       IQ binary file (interleaved int8 I/Q)
#   --center-freq HZ  Center frequency in Hz (default: 5.84e9)
#   --sample-rate HZ  Sample rate in Hz (default: 20e6)
#   --fft-size N      FFT size (default: 4096)
#   --alpha A         EMA smoothing factor for the spectrum (default: 0.2)


parser = argparse.ArgumentParser(description="Replay an IQ file as a live spectrum plot")
parser.add_argument("--file", required=True, metavar="PATH",
                    help="IQ binary file (interleaved int8 I/Q)")
parser.add_argument("--center-freq", type=float, default=5840e6, metavar="HZ",
                    help="Center frequency in Hz (default: 5.84e9)")
parser.add_argument("--sample-rate", type=float, default=20e6, metavar="HZ",
                    help="Sample rate in Hz (default: 20e6)")
parser.add_argument("--fft-size", type=int, default=4096, metavar="N",
                    help="FFT size (default: 4096)")
parser.add_argument("--alpha", type=float, default=0.2, metavar="A",
                    help="EMA smoothing factor for the spectrum (default: 0.2)")
args = parser.parse_args()

FILE        = args.file
CENTER_FREQ = args.center_freq
SAMPLE_RATE = args.sample_rate
FFT_SIZE    = args.fft_size
ALPHA       = args.alpha

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
