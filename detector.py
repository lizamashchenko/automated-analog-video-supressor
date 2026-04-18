import threading
import numpy as np

from utils.logger import SDRLogger
from plateau_detector.plateau_detector import PlateauDetector
from video_classifiers.harmonic_classifier import HarmonicClassifier
from video_classifiers.cyclo_classifier import CycloClassifier
from video_classifiers.autocorrelation_classifier import AutocorrClassifier
from utils.spectrum_manipulation import compute_power_spectrum, get_freq_key

class ScanState:
    def __init__(self):
        self.avg_power      = None
        self.avg_power_map  = {}
        self.plateau_map    = {}

class Detector:
    def __init__(self, cfg, on_event = None):
        self.cfg            = cfg
        self.on_event       = on_event or (lambda t, d: None)
        self._stop          = threading.Event()
        self._thread        = None
        self.device         = None
        self.reader         = None
        self.pl_detector    = None
        self.classifier     = None
        self.log            = None

    def start(self, run_name=None):
        self._stop.clear()
        self._thread = threading.Thread(
            target  = self._run, 
            args    = (run_name,), 
            daemon  = True
        )
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout = 15)

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def _setup(self, run_name):
        cfg = self.cfg

        self.log = SDRLogger(
            base_log_dir    = cfg["logging"]["base_dir"],
            run_name        = run_name,
            sample_rate     = cfg["sdr"]["sample_rate"],
            verbosity       = cfg["logging"]["verbosity"]
        )

        dev_cfg = cfg["device"]
        if dev_cfg["type"] == "hackrf":
            from rf_devices.hackrf_device import HackRFDevice
            self.device = HackRFDevice(
                sample_rate = cfg["sdr"]["sample_rate"],
                lna_gain    = cfg["sdr"]["lna_gain"],
                vga_gain    = cfg["sdr"]["vga_gain"]
            )
        elif dev_cfg["type"] == "file":
            from rf_devices.file_devicie import FileDevice
            self.device = FileDevice(
                filepath        = dev_cfg["file_path"],
                metadata_path   = dev_cfg["metadata_path"],
                sample_rate     = cfg["sdr"]["sample_rate"]
            )
        else:
            raise ValueError(f"Unknown device type: {dev_cfg['type']!r}")

        from sdr_reader.reader_runner import SDRReader
        self.reader = SDRReader(
            self.device,
            buffer_size = cfg["sdr"]["buffer_size"],
            logger      = self.log
        )

        pl_cfg = cfg["plateau"]
        self.pl_detector = PlateauDetector(
            sample_rate             = cfg["sdr"]["sample_rate"],
            fft_size                = cfg["fft"]["fft_size"],
            wide_sampling_num       = cfg["scan"]["wide_sampling_num"],
            freq_tolerance          = pl_cfg["freq_tolerance"],
            above_noise_threshold   = pl_cfg["above_noise_threshold"],
            edge_drop_level         = pl_cfg["edge_drop_level"],
            min_lobe_size           = pl_cfg["min_lobe_size"],
            lobe_merge_gap          = pl_cfg["lobe_merge_gap"],
            min_video_width         = pl_cfg["min_video_width"],
            max_video_width         = pl_cfg["max_video_width"],
            plateau_required_ratio  = pl_cfg["required_ratio"],
            logger                  = self.log
        )

        active = cfg["detection"]["active_classifier"]
        if active == "harmonic":
            h = cfg["classifier"]["harmonic"]
            self.classifier = HarmonicClassifier(
                required_harmonics     = h["required_harmonics"],
                harmonic_ratio         = h["harmonic_ratio"],
                threshold_db           = h["threshold_db"],
                valley_drop_db         = h["valley_drop_db"],
                max_harmonic_spread_db = h["max_harmonic_spread_db"],
                target_freq            = h["target_freq"],
                sync_band              = h["sync_band"],
                harmonics              = h["harmonics"],
                logger                 = self.log
            )
        elif active == "cyclo":
            c = cfg["classifier"]["cyclo"]
            self.classifier = CycloClassifier(
                sample_rate     = cfg["sdr"]["sample_rate"],
                fft_size        = cfg["fft"]["fft_size"],
                ratio_threshold = c["ratio_threshold"],
                score_threshold = c["score_threshold"],
                required_votes  = c["required_votes"],
                target_freq     = c["target_freq"],
                harmonics       = c["harmonics"],
                min_harmonics   = c.get("min_harmonics", 2),
                max_harmonic_spread_db = c.get("max_harmonic_spread_db", 15),
                logger          = self.log
            )
        elif active == "autocorr":
            a = cfg["classifier"]["autocorr"]
            self.classifier = AutocorrClassifier(
                sample_rate         = cfg["sdr"]["sample_rate"],
                decimation          = a["decimation"],
                line_freq           = a["line_freq"],
                lag_tolerance       = a["lag_tolerance"],
                peak_threshold      = a["peak_threshold"],
                secondary_threshold = a["secondary_threshold"],
                lag_strict          = a["lag_strict"],
                required_votes      = a["required_votes"],
                logger              = self.log
            )
        else:
            raise ValueError(f"Unknown classifier: {active!r}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self, run_name):
        try:
            self._setup(run_name)
            self.reader.start()
            self._emit("status", {"state": "running", "run_name": self.log.run_id})

            cfg = self.cfg
            min_freq  = cfg["sdr"]["min_freq"]
            max_freq  = cfg["sdr"]["max_freq"]
            max_sweeps = cfg.get("sweeps", 0)

            sweep = 0
            while not self._stop.is_set():
                if max_sweeps > 0 and sweep >= max_sweeps:
                    break
                self._sweep(sweep, min_freq, max_freq)
                sweep += 1

        except Exception as e:
            self._emit("error", {"error_type": "DETECTOR_ERROR", "message": str(e)})
            raise
        finally:
            if self.reader:
                self.reader.stop()
            if self.device:
                self.device.close()
            self._emit("status", {"state": "stopped"})

    def _sweep(self, sweep_num, min_freq, max_freq):
        cfg = self.cfg

        sample_rate       = cfg["sdr"]["sample_rate"]
        wide_sampling_num = cfg["scan"]["wide_sampling_num"]
        freq_tolerance    = cfg["plateau"]["freq_tolerance"]
        max_samples       = cfg["demod"]["max_samples_per_plateau"]
        required_ratio    = cfg["plateau"]["required_ratio"]
        required_hits     = int(wide_sampling_num * required_ratio)

        state = ScanState()
        current_freq = min_freq
        freq_range = max_freq - min_freq
        plateau_count = 0

        self._emit("sweep_start", {
            "sweep_num": sweep_num,
            "min_freq": min_freq,
            "max_freq": max_freq
        })

        while current_freq < max_freq and not self._stop.is_set():
            key = get_freq_key(current_freq)
            progress = (current_freq - min_freq) / freq_range

            self._emit("freq_update", {
                "freq": current_freq,
                "progress": round(progress, 3)
            })

            if key in state.avg_power_map:
                state.avg_power = state.avg_power_map[key].copy()
            else:
                state.avg_power = None

            detections = []
            all_samples = []
            self.device.tune(current_freq)

            for _ in range(wide_sampling_num):
                if self._stop.is_set():
                    break
                samples = self.reader.get_samples()

                if samples is None:
                    self.log.log_event("ZERO_BUFFER", "All samples are zero", level=1, freq=current_freq)
                    self._emit("error", {"error_type": "ZERO_BUFFER", "message": "Zero buffer", "freq": current_freq})
                    continue

                power = compute_power_spectrum(samples, state)
                plateaus = self.pl_detector.detect(power, current_freq)
                all_samples.append(samples)

                if plateaus:
                    detections.append((samples, plateaus))

            if state.avg_power is not None:
                self._emit("spectrum", {"freq": current_freq, "power": _downsample(state.avg_power, 256)})

            plateau = self.pl_detector.validate(detections)

            if not plateau:
                if len(detections) > 0:
                    self.log.log_event("PLATEAU_REJECTED", "Not enough hits", level = 2, hits = len(detections), required = required_hits, freq = current_freq)
                    self._emit("plateau_rejected", { "freq": current_freq, "hits": len(detections), "required": required_hits })
                current_freq += sample_rate
                continue

            plateau["samples"] = all_samples
            plateau_count += 1

            self.log.log_confirmed_plateau(plateau["center_freq"], plateau["bandwidth"], len(detections))
            self.log.log_event("PLATEAU_CONFIRMED", "Wideband signal detected", level = 2, freq = plateau["center_freq"], bw = plateau["bandwidth"], hits = len(detections))
            self._emit("plateau_confirmed", {
                "freq":         plateau["center_freq"],
                "bandwidth":    plateau["bandwidth"],
                "hits":         len(detections),
                "sweep_num":    sweep_num
            })

            self.pl_detector.update_map(state.plateau_map, plateau)
            if state.avg_power is not None:
                state.avg_power_map[key] = state.avg_power.copy()

            current_freq += sample_rate

        for key, samples_list in state.plateau_map.items():
            if self._stop.is_set():
                break

            if len(samples_list) < max_samples:
                continue

            center_freq = key * freq_tolerance
            result = self.classifier.classify(samples_list, sample_rate, center_freq)

            if result["confirmed"]:
                self.log.log_video_detection(center_freq, result["score"], len(samples_list))
                self.log.log_event("VIDEO_CONFIRMED", f"{self.classifier.name} confirmed video", level = 2, freq = center_freq, score = result["score"])
                self.log.log_video_samples(center_freq, samples_list)
                self._emit("video_confirmed", {
                    "freq":         center_freq,
                    "classifier":   self.classifier.name,
                    "score":        result["score"],
                    "sweep_num":    sweep_num
                })

            elif (center_freq > 5_830_000_000 and center_freq < 5_860_000_000):
                self.log.log_video_samples(center_freq, samples_list) 

            else:
                self.log.log_event("VIDEO_REJECTED", f"{self.classifier.name} rejected video", level = 2, freq = center_freq, score = result["score"])
                self._emit("video_rejected", {
                    "freq":         center_freq,
                    "classifier":   self.classifier.name,
                    "score":        result["score"],
                    "sweep_num":    sweep_num
                })

        self._emit("sweep_complete", { "sweep_num": sweep_num, "plateaus": plateau_count})

    def _emit(self, event_type, data):
        self.on_event(event_type, data)

def _downsample(power, n_bins):
    arr = np.asarray(power, dtype = float)
    chunk = max(1, len(arr) // n_bins)
    return [float(np.mean(arr[i * chunk:(i + 1) * chunk])) for i in range(n_bins)]
