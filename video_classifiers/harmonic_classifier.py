import numpy as np
from .base import VideoClassifier


class HarmonicClassifier(VideoClassifier):
    def __init__(
        self,
        required_hits = 3,
        required_votes = 4,
        threshold_db = 5,
        target_freq = 15625,
        sync_band = 2000,
        harmonics = None,
        logger = None
    ):
        super().__init__("harmonic")
        self.required_hits = required_hits
        self.required_votes = required_votes
        self.threshold_db = threshold_db
        self.target_freq = target_freq
        self.sync_band = sync_band
        self.harmonics = harmonics if harmonics is not None else [1, 2, 3, 4]
        self.logger = logger

    def classify(self, samples_list, sample_rate, center_freq):
        votes = 0

        for samples in samples_list:
            samples = samples[:4096]

            demod = np.angle(samples[1:] * np.conj(samples[:-1]))
            fft = np.fft.fftshift(np.fft.fft(demod * np.hanning(len(demod))))
            power = 20 * np.log10(np.abs(fft) + 1e-12)
            freqs = np.linspace(-sample_rate/2, sample_rate/2, len(demod))

            base_noise = np.median(power)

            hits = 0

            for h in self.harmonics:
                f = h * self.target_freq

                mask = (np.abs(freqs - f) < self.sync_band) | \
                       (np.abs(freqs + f) < self.sync_band)

                if np.mean(power[mask]) - base_noise > self.threshold_db:
                    hits += 1

            if hits >= self.required_hits:
                votes += 1

        if self.logger:
            self.logger.log_debug_event(
                "harmonic",
                "HARMONIC_RESULT",
                "Harmonic classification result",
                res = (votes >= self.required_votes),
                freq = center_freq,
                hits = hits,
                votes = votes,
                required = self.required_votes
            )

        return {
            "confirmed": votes >= self.required_votes,
            "score": votes,
            "details": {
                "required_votes": self.required_votes,
                "base_noise": base_noise
            }
        }