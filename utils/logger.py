from datetime import datetime
import os
import numpy as np


class SDRLogger:
    def __init__(self, base_log_dir="logs", run_name=None, sample_rate=None, verbosity=1):
        self.base_log_dir = base_log_dir
        self.sample_rate = sample_rate
        self.verbosity = verbosity

        self.run_id = run_name or datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_dir = os.path.join(self.base_log_dir, self.run_id)
        os.makedirs(self.log_dir, exist_ok=True)

        self.general_log          = os.path.join(self.log_dir, "events.log")
        self.confirmed_plateau_log = os.path.join(self.log_dir, "confirmed_plateau.log")
        self.video_log            = os.path.join(self.log_dir, "video_detections.log")

        self._debug_logs = {}
        self._samples_dir = None

    def log_event(self, event_type, message, level=1, **kwargs):
        if self.verbosity < 1 or level > self.verbosity:
            return

        timestamp = datetime.utcnow().isoformat()
        extra = ",".join(f"{k}={v}" for k, v in kwargs.items())
        line = f"{timestamp},{event_type},{message}"

        if extra:
            line += "," + extra

        with open(self.general_log, "a") as f:
            f.write(line + "\n")

    def log_confirmed_plateau(self, freq, bw, hits):
        if self.verbosity < 1:
            return
        with open(self.confirmed_plateau_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{bw:.3f},{hits}\n")

    def log_video_detection(self, freq, score, sample_count):
        with open(self.video_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{score:.2f},{sample_count}\n")

    def log_debug_event(self, component, event_type, message, **kwargs):
        if self.verbosity < 3:
            return

        path = self._debug_log_path(component)
        timestamp = datetime.utcnow().isoformat()
        extra = ",".join(f"{k}={v}" for k, v in kwargs.items())
        line = f"{timestamp},{event_type},{message}"

        if extra:
            line += "," + extra

        with open(path, "a") as f:
            f.write(line + "\n")

    def _debug_log_path(self, component):
        if component not in self._debug_logs:
            self._debug_logs[component] = os.path.join(
                self.log_dir, f"{component}_debug.log"
            )

        return self._debug_logs[component]

    def log_video_samples(self, center_freq, samples_list):
        if self.verbosity < 4:
            return

        samples_dir = self._ensure_samples_dir()
        timestamp = datetime.utcnow().strftime("%H-%M-%S-%f")
        freq_mhz = center_freq / 1e6
        filename = f"{freq_mhz:.1f}MHz_{timestamp}.npy"

        np.save(os.path.join(samples_dir, filename), np.array(samples_list))

    def _ensure_samples_dir(self):
        if self._samples_dir is None:
            self._samples_dir = os.path.join(self.log_dir, "samples")
            os.makedirs(self._samples_dir, exist_ok=True)

        return self._samples_dir

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
