import argparse
import csv
import os
import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtWidgets, QtCore
import threading
import time
import sys


# usage: plot_iq.py [-h] (--dir DIR | --file PATH --meta PATH) [--sample-rate HZ] [--fft-size N] [--alpha A] [--chunk-delay S] [--start-freq HZ] [--stop-freq HZ]

# Replay a sweep recorded by iq_capture.py as a stitched spectrum plot.
# The x-axis stays fixed over the full swept range; each band fills in
# (and updates via EMA) as its chunks are processed.


parser = argparse.ArgumentParser(description="Replay an iq_capture sweep as a stitched spectrum plot")
parser.add_argument("--dir", metavar="DIR",
                    help="Sweep directory containing iq.bin and metadata.csv")
parser.add_argument("--file", metavar="PATH",
                    help="IQ binary file (complex64). Overrides <dir>/iq.bin")
parser.add_argument("--meta", metavar="PATH",
                    help="metadata.csv path. Overrides <dir>/metadata.csv")
parser.add_argument("--sample-rate", type=float, default=20e6, metavar="HZ",
                    help="Sample rate in Hz (default: 20e6)")
parser.add_argument("--fft-size", type=int, default=4096, metavar="N",
                    help="FFT size (default: 4096)")
parser.add_argument("--alpha", type=float, default=0.2, metavar="A",
                    help="EMA smoothing factor for the spectrum (default: 0.2)")
parser.add_argument("--chunk-delay", type=float, default=0.0, metavar="S",
                    help="Seconds to sleep between FFT updates (default: 0)")
parser.add_argument("--start-freq", type=float, default=None, metavar="HZ",
                    help="Skip chunks with center_freq below this (Hz)")
parser.add_argument("--stop-freq", type=float, default=None, metavar="HZ",
                    help="Skip chunks with center_freq above this (Hz)")
args = parser.parse_args()

if args.dir:
    IQ_FILE   = args.file or os.path.join(args.dir, "iq.bin")
    META_FILE = args.meta or os.path.join(args.dir, "metadata.csv")
elif args.file and args.meta:
    IQ_FILE   = args.file
    META_FILE = args.meta
else:
    parser.error("Provide --dir, or both --file and --meta")

SAMPLE_RATE = args.sample_rate
FFT_SIZE    = args.fft_size
ALPHA       = args.alpha
CHUNK_DELAY = args.chunk_delay

chunks = []
with open(META_FILE, newline="") as mf:
    for row in csv.DictReader(mf):
        cf = float(row["center_freq"])
        if args.start_freq is not None and cf < args.start_freq:
            continue
        if args.stop_freq is not None and cf > args.stop_freq:
            continue
        chunks.append({
            "center_freq":  cf,
            "offset_bytes": int(row["offset_bytes"]),
            "num_samples":  int(row["num_samples"]),
        })

if not chunks:
    sys.exit(f"[ERROR] no chunks found in {META_FILE} (check --start-freq/--stop-freq)")

unique_freqs = sorted({c["center_freq"] for c in chunks})
freq_index = {cf: i for i, cf in enumerate(unique_freqs)}
NUM_BANDS = len(unique_freqs)

full_freqs = np.concatenate([
    np.linspace(cf - SAMPLE_RATE/2, cf + SAMPLE_RATE/2, FFT_SIZE) / 1e6
    for cf in unique_freqs
])
full_power = np.full(NUM_BANDS * FFT_SIZE, np.nan, dtype=np.float32)
band_avg   = [None] * NUM_BANDS

print(f"[INFO] replaying {len(chunks)} chunks across {NUM_BANDS} bands, "
      f"{unique_freqs[0]/1e6:.1f}–{unique_freqs[-1]/1e6:.1f} MHz")

lock = threading.Lock()
dirty = False


def file_worker():
    global dirty

    f = open(IQ_FILE, "rb")

    while True:
        for chunk in chunks:
            f.seek(chunk["offset_bytes"])
            bi = freq_index[chunk["center_freq"]]

            remaining = chunk["num_samples"]
            while remaining >= FFT_SIZE:
                samples = np.fromfile(f, dtype=np.complex64, count=FFT_SIZE)
                if len(samples) < FFT_SIZE:
                    break
                remaining -= FFT_SIZE

                window = np.hanning(len(samples))
                spectrum = np.fft.fftshift(np.fft.fft(samples * window))
                power = 20 * np.log10(np.abs(spectrum) + 1e-12)

                center = len(power) // 2
                power[center-5:center+5] = np.median(power)

                prev = band_avg[bi]
                band_avg[bi] = power if prev is None else ALPHA * power + (1 - ALPHA) * prev

                with lock:
                    full_power[bi*FFT_SIZE:(bi+1)*FFT_SIZE] = band_avg[bi]
                    dirty = True

                if CHUNK_DELAY:
                    time.sleep(CHUNK_DELAY)

        print("[INFO] Reached end of sweep, looping...")


thread = threading.Thread(target=file_worker, daemon=True)
thread.start()

app = QtWidgets.QApplication(sys.argv)

win = pg.GraphicsLayoutWidget(title="IQ Sweep Replay")
plot = win.addPlot(title=f"Spectrum {unique_freqs[0]/1e6:.0f}–{unique_freqs[-1]/1e6:.0f} MHz")

curve = plot.plot(pen='y')

plot.setLabel('left', 'Power', 'dB')
plot.setLabel('bottom', 'Frequency', 'MHz')
plot.enableAutoRange('y', True)
plot.setXRange(full_freqs[0], full_freqs[-1])

win.show()


def update():
    global dirty

    with lock:
        if not dirty:
            return
        data = full_power.copy()
        dirty = False

    mask = ~np.isnan(data)
    if not mask.any():
        return
    curve.setData(full_freqs[mask], data[mask])


timer = QtCore.QTimer()
timer.timeout.connect(update)
timer.start(100)

sys.exit(app.exec())
