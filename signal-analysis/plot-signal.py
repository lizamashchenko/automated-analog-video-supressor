import numpy as np

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt

from matplotlib.widgets import Slider


FILE = "/home/liza/UCU/diploma/dataset/spectrum_recordings/rec-0001.csv"


sweeps = []
current_freqs = []
current_power = []

first_freq = None


with open(FILE) as f:
    for line in f:

        parts = [p.strip(',') for p in line.split()]

        start_freq = float(parts[2])
        bin_width = float(parts[4])
        power_values = np.array(parts[6:], dtype=float)

        if first_freq is None:
            first_freq = start_freq

        # detect sweep boundary
        if start_freq == first_freq and len(current_freqs) > 0:
            freqs = np.concatenate(current_freqs)
            power = np.concatenate(current_power)

            idx = np.argsort(freqs)
            sweeps.append((freqs[idx], power[idx]))

            current_freqs = []
            current_power = []

        freqs = start_freq + np.arange(len(power_values)) * bin_width

        current_freqs.append(freqs)
        current_power.append(power_values)

if current_freqs:
    freqs = np.concatenate(current_freqs)
    power = np.concatenate(current_power)
    idx = np.argsort(freqs)
    sweeps.append((freqs[idx], power[idx]))

print("Loaded sweeps:", len(sweeps))

fig, ax = plt.subplots(figsize=(14,5))
plt.subplots_adjust(bottom=0.25)

freqs, power = sweeps[0]
line, = ax.plot(freqs/1e6, power, lw=0.6)

ax.set_xlabel("Frequency (MHz)")
ax.set_ylabel("Power (dB)")
ax.set_title("HackRF Sweep Replay")
ax.grid(True)

# slider
ax_slider = plt.axes([0.2, 0.1, 0.6, 0.03])
slider = Slider(ax_slider, "Sweep", 0, len(sweeps)-1, valinit=0, valstep=1)

def update(val):
    i = int(slider.val)
    freqs, power = sweeps[i]

    line.set_data(freqs/1e6, power)
    ax.relim()
    ax.autoscale_view()

    fig.canvas.draw_idle()

slider.on_changed(update)
plt.show()