import numpy as np
from .base import VideoClassifier


class HarmonicClassifier(VideoClassifier):
    def __init__(
        self,
        required_harmonics     = 2,
        harmonic_ratio         = 0.4,
        threshold_db           = 6,
        valley_drop_db         = 4,
        max_harmonic_spread_db = 15,
        target_freq            = 15625,
        sync_band              = 2000,
        harmonics              = None,
        logger                 = None
    ):
        super().__init__("harmonic")
        self.required_harmonics     = required_harmonics
        self.harmonic_ratio         = harmonic_ratio
        self.threshold_db           = threshold_db
        self.valley_drop_db         = valley_drop_db
        self.max_harmonic_spread_db = max_harmonic_spread_db
        self.target_freq            = target_freq
        self.sync_band              = sync_band
        # harmonics includes 0 (near-DC) so peaks are at 0, f, 2f, 3f, ...
        self.harmonics              = harmonics if harmonics is not None else [0, 1, 2, 3]
        self.logger                 = logger

    def _band_mean(self, power, freqs, center):
        mask = np.abs(freqs - center) < self.sync_band
        if not mask.any():
            return None
        return float(np.mean(power[mask]))

    def classify(self, samples_list, sample_rate, center_freq):
        hit_counts = {h: 0 for h in self.harmonics}
        total      = len(samples_list)
        base_noise = 0.0

        for samples in samples_list:
            samples = samples[:4096]

            demod = np.angle(samples[1:] * np.conj(samples[:-1]))
            fft   = np.fft.fftshift(np.fft.fft(demod * np.hanning(len(demod))))
            power = 20 * np.log10(np.abs(fft) + 1e-12)

            # Positive frequencies only
            n     = len(power)
            power = power[n // 2:]
            freqs = np.linspace(0, sample_rate / 2, len(power))

            base_noise = float(np.median(power))
            per_harmonic   = {}
            per_buffer_hit = {}
            peak_vals      = []

            for h in self.harmonics:
                peak_freq   = h * self.target_freq
                valley_freq = (h + 0.5) * self.target_freq

                peak_val   = self._band_mean(power, freqs, peak_freq)
                valley_val = self._band_mean(power, freqs, valley_freq)

                if peak_val is None or valley_val is None:
                    per_harmonic[h] = None
                    continue

                above_noise    = peak_val - base_noise
                peak_to_valley = peak_val - valley_val

                per_harmonic[h] = {
                    "above_noise":    round(above_noise, 2),
                    "peak_to_valley": round(peak_to_valley, 2),
                }
                peak_vals.append(peak_val)

                per_buffer_hit[h] = (
                    above_noise   > self.threshold_db and
                    peak_to_valley > self.valley_drop_db
                )

            # Adjacent-peak spread check: reject buffers where harmonics have
            # wildly different levels (e.g. a huge DC spike with flat rest),
            # since a real video comb has a smooth rolloff between peaks.
            if len(peak_vals) >= 2:
                max_spread = max(
                    abs(peak_vals[j + 1] - peak_vals[j])
                    for j in range(len(peak_vals) - 1)
                )
            else:
                max_spread = 0.0

            spread_ok = max_spread <= self.max_harmonic_spread_db

            if spread_ok:
                for h, hit in per_buffer_hit.items():
                    if hit:
                        hit_counts[h] += 1

            if self.logger:
                self.logger.log_debug_event(
                    "harmonic",
                    "HARMONIC_SAMPLE",
                    "Per-buffer harmonic result",
                    freq       = center_freq,
                    base_noise = round(base_noise, 2),
                    max_spread = round(max_spread, 2),
                    spread_ok  = spread_ok,
                    harmonics  = per_harmonic,
                )

        confirmed_harmonics = {
            h: count
            for h, count in hit_counts.items()
            if total > 0 and count / total >= self.harmonic_ratio
        }
        confirmed = len(confirmed_harmonics) >= self.required_harmonics

        if self.logger:
            self.logger.log_event(
                "HARMONIC_RESULT",
                "Harmonic classification result",
                level               = 2,
                freq                = center_freq,
                confirmed           = confirmed,
                confirmed_harmonics = len(confirmed_harmonics),
                required            = self.required_harmonics,
                hit_counts          = hit_counts,
                total_buffers       = total,
            )

        return {
            "confirmed": confirmed,
            "score":     len(confirmed_harmonics),
            "details": {
                "confirmed_harmonics": confirmed_harmonics,
                "hit_counts":          hit_counts,
                "total_buffers":       total,
                "base_noise":          base_noise,
            }
        }
