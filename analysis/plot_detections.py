import argparse
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.signal import decimate

LINE_FREQ   = 15_625
HARMONICS   = [1, 2, 3, 4]
DECIM_RATE  = None

def fm_demod(iq):
    inst = np.angle(iq[1:] * np.conj(iq[:-1]))
    inst -= np.mean(inst)
    return inst

def power_spectrum(signal, sample_rate):
    n = len(signal)
    win = np.hanning(n)
    fft = np.fft.rfft(signal * win)
    freqs = np.fft.rfftfreq(n, 1 / sample_rate)
    power_db = 20 * np.log10(np.abs(fft) + 1e-12)
    return freqs, power_db

def autocorrelation(signal, sample_rate, line_freq=LINE_FREQ, lag_tolerance=0.1):
    q = max(1, int(sample_rate // 1_000_000))
    if q > 1:
        signal = decimate(signal, q, ftype="fir", zero_phase=True)
    fs_eff = sample_rate / q

    corr = np.correlate(signal, signal, mode="full")
    corr = corr[len(corr) // 2:]
    if corr[0] < 1e-12:
        return None, None, None
    corr /= corr[0]

    target_lag = int(round(fs_eff / line_freq))
    lags = np.arange(len(corr)) / fs_eff * 1000  # ms

    return lags, corr, target_lag / fs_eff * 1000

HARMONIC_COLORS = ["#e74c3c", "#e67e22", "#2ecc71", "#3498db"]

def plot_sample(npy_path, sample_rate, out_path):
    data = np.load(npy_path)
    center_freq_mhz = float(os.path.basename(npy_path).split("MHz")[0])

    if data.ndim == 1:
        data = data[np.newaxis, :]

    power_sum = None
    freqs = None
    corr_sum = None
    lags = None
    target_lag_ms = None
    n_valid = 0

    for iq in data:
        demod = fm_demod(iq)

        f, p = power_spectrum(demod, sample_rate)
        if power_sum is None:
            power_sum = p
            freqs = f
        else:
            power_sum += p

        l, c, tlm = autocorrelation(demod, sample_rate)
        if c is not None:
            if corr_sum is None:
                corr_sum = c
                lags = l
                target_lag_ms = tlm
            else:
                min_len = min(len(corr_sum), len(c))
                corr_sum = corr_sum[:min_len] + c[:min_len]
                lags = lags[:min_len]
        n_valid += 1

    power = power_sum / n_valid
    if corr_sum is not None:
        corr = corr_sum / n_valid
    else:
        corr = None

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(
        f"Demodulated baseband — {center_freq_mhz:.1f} MHz",
        fontsize=13, fontweight="bold"
    )

    ax = axes[0]
    ax.plot(freqs / 1e3, power, color="#2c3e50", linewidth=0.8, label="FM demod")

    noise_floor = np.median(power)
    ax.axhline(noise_floor, color="gray", linestyle=":", linewidth=0.8, label="Noise floor (median)")

    for i, h in enumerate(HARMONICS):
        f_khz = h * LINE_FREQ / 1e3
        ax.axvline(f_khz, color=HARMONIC_COLORS[i], linestyle="--", linewidth=1.2,
                   label=f"{h}× {LINE_FREQ/1e3:.3f} kHz")

    ax.set_xlabel("Frequency (kHz)")
    ax.set_ylabel("Power (dB)")
    ax.set_title("FM-demodulated power spectrum")
    ax.set_xlim(0, min(freqs[-1] / 1e3, 200))
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator())
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator())

    ax2 = axes[1]
    if lags is not None:
        max_lag_ms = 5 * (1000 / LINE_FREQ)
        mask = lags <= max_lag_ms
        ax2.plot(lags[mask], corr[mask], color="#2c3e50", linewidth=0.8)
        ax2.axvline(target_lag_ms, color="#e74c3c", linestyle="--", linewidth=1.5,
                    label=f"1 line period ({target_lag_ms:.3f} ms)")
        ax2.axhline(0, color="gray", linestyle=":", linewidth=0.8)
        ax2.set_xlabel("Lag (ms)")
        ax2.set_ylabel("Normalised autocorrelation")
        ax2.set_title("Autocorrelation of FM-demodulated signal")
        ax2.legend(fontsize=8)
        ax2.grid(True, alpha=0.3)
    else:
        ax2.text(0.5, 0.5, "Autocorrelation unavailable", ha="center", va="center",
                 transform=ax2.transAxes)

    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)

def process_dir(log_dir, sample_rate):
    samples_dir = os.path.join(log_dir, "samples")
    if not os.path.isdir(samples_dir):
        print(f"  [skip] no samples/ directory in {log_dir}")
        return 0

    npy_files = sorted(f for f in os.listdir(samples_dir) if f.endswith(".npy"))
    if not npy_files:
        print(f"  [skip] no .npy files in {samples_dir}")
        return 0

    count = 0
    for fname in npy_files:
        npy_path = os.path.join(samples_dir, fname)
        out_path = npy_path.replace(".npy", ".png")
        print(f"  plotting {fname} -> {os.path.basename(out_path)}")
        try:
            plot_sample(npy_path, sample_rate, out_path)
            count += 1
        except Exception as e:
            print(f"  [error] {fname}: {e}")

    return count

def main():
    parser = argparse.ArgumentParser(description="Plot demodulated baseband for saved IQ samples")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--log-dir", metavar="DIR",
                       help="Single log directory")
    group.add_argument("--run-name", metavar="NAME",
                       help="Run name prefix (processes all matching classifier dirs)")
    parser.add_argument("--classifier", choices=["harmonic", "cyclo", "autocorr"],
                        help="Only process this classifier (used with --run-name)")
    parser.add_argument("--logs-base", metavar="DIR", default="logs",
                        help="Base logs directory (default: logs)")
    parser.add_argument("--sample-rate", type=float, default=20e6,
                        help="IQ sample rate in Hz (default: 20000000)")
    args = parser.parse_args()

    if args.log_dir:
        dirs = [args.log_dir]
    else:
        classifiers = [args.classifier] if args.classifier else ["harmonic", "cyclo", "autocorr"]
        dirs = [
            os.path.join(args.logs_base, f"{args.run_name}_{clf}")
            for clf in classifiers
            if os.path.isdir(os.path.join(args.logs_base, f"{args.run_name}_{clf}"))
        ]
        if not dirs:
            print("No matching run directories found.")
            return

    total = 0
    for d in dirs:
        print(f"\n{d}")
        total += process_dir(d, args.sample_rate)

    print(f"\nDone. {total} plot(s) saved.")

if __name__ == "__main__":
    main()
