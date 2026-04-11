from datetime import datetime
import os
import numpy as np


class SDRLogger:
    """
    Verbosity levels
    ----------------
    1  errors + dedicated detection logs (events.log, confirmed_plateau.log, video_detections.log)
    2  level 1 + plateau/video approved/rejected decisions in events.log
    3  level 2 + per-component debug files ({component}_debug.log)
    4  level 3 + raw IQ samples saved to samples/ on confirmed video
    """

    def __init__(self, base_log_dir="logs", run_name=None, sample_rate=None, verbosity=1):
        self.base_log_dir = base_log_dir
        self.sample_rate = sample_rate
        self.verbosity = verbosity

        self.run_id = run_name or datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        self.log_dir = os.path.join(self.base_log_dir, self.run_id)
        os.makedirs(self.log_dir, exist_ok=True)

        # Level 1 — always created
        self.general_log          = os.path.join(self.log_dir, "events.log")
        self.confirmed_plateau_log = os.path.join(self.log_dir, "confirmed_plateau.log")
        self.video_log            = os.path.join(self.log_dir, "video_detections.log")

        # Level 3 — one debug log per component, opened lazily
        self._debug_logs = {}

        # Level 4 — samples subdirectory, created lazily
        self._samples_dir = None

    # -----------------------------
    # Level 1 — generic event log
    # -----------------------------
    def log_event(self, event_type, message, level=1, **kwargs):
        """Write to events.log only if level <= verbosity."""
        if level > self.verbosity:
            return
        timestamp = datetime.utcnow().isoformat()
        extra = ",".join(f"{k}={v}" for k, v in kwargs.items())
        line = f"{timestamp},{event_type},{message}"
        if extra:
            line += "," + extra
        with open(self.general_log, "a") as f:
            f.write(line + "\n")

    # -----------------------------
    # Level 1 — dedicated log files
    # -----------------------------
    def log_confirmed_plateau(self, freq, bw, hits):
        with open(self.confirmed_plateau_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{bw:.3f},{hits}\n")

    def log_video_detection(self, freq, score, sample_count):
        with open(self.video_log, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()},{freq:.3f},{score:.2f},{sample_count}\n")

    # -----------------------------
    # Level 3 — per-component debug
    # -----------------------------
    def log_debug_event(self, component, event_type, message, **kwargs):
        """Write to {component}_debug.log. Only active at verbosity >= 3."""
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

    # -----------------------------
    # Level 4 — raw IQ samples
    # -----------------------------
    def log_video_samples(self, center_freq, samples_list):
        """Save IQ buffers for a confirmed video hit as a .npy file."""
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
