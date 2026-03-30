from datetime import datetime
import os
import numpy as np


class SDRLogger:
    def __init__(self, base_log_dir="logs", sample_rate=None):
        self.base_log_dir = base_log_dir
        self.sample_rate = sample_rate

        self.run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_dir = os.path.join(self.base_log_dir, self.run_id)

        os.makedirs(self.log_dir, exist_ok=True)

        # File paths
        self.general_log = os.path.join(self.log_dir, "events.log")
        self.possible_plateau_log = os.path.join(self.log_dir, "possible_plateau.log")
        self.confirmed_plateau_log = os.path.join(self.log_dir, "confirmed_plateau.log")
        self.video_log = os.path.join(self.log_dir, "video_detections.log")

    # -----------------------------
    # Generic logging
    # -----------------------------
    def log_event(self, event_type, message, **kwargs):
        timestamp = datetime.utcnow().isoformat()
        extra = ",".join(f"{k}={v}" for k, v in kwargs.items())

        line = f"{timestamp},{event_type},{message}"
        if extra:
            line += "," + extra

        with open(self.general_log, "a") as f:
            f.write(line + "\n")

    # -----------------------------
    # Specific logs
    # -----------------------------
    def log_possible_plateau(self, freq, bw, bin_idx):
        with open(self.possible_plateau_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{bw:.3f},{bin_idx}\n")

    def log_confirmed_plateau(self, freq, bw, hits):
        with open(self.confirmed_plateau_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{bw:.3f},{hits}\n")

    def log_video_detection(self, freq, pos_peak, neg_peak):
        with open(self.video_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{pos_peak:.2f},{neg_peak:.2f}\n")

    # -----------------------------
    # Spectrum visualization
    # -----------------------------
    def print_spectrum_bar(self, avg_power, center_freq, bins=80):
        if self.sample_rate is None:
            raise ValueError("sample_rate must be set to use print_spectrum_bar")

        chunk_size = len(avg_power) // bins
        compressed = [
            np.mean(avg_power[i * chunk_size:(i + 1) * chunk_size])
            for i in range(bins)
        ]

        min_val, max_val = np.min(compressed), np.max(compressed)
        scaled = [(val - min_val) / (max_val - min_val + 1e-6) for val in compressed]

        bars = "▁▂▃▄▅▆▇█"
        line = "".join(bars[int(s * 7)] for s in scaled)

        print(line)
        print(
            f"{(center_freq - self.sample_rate / 2) / 1e6:.2f} MHz"
            f"{' ' * (bins - 10)}"
            f"{(center_freq + self.sample_rate / 2) / 1e6:.2f} MHz"
        )