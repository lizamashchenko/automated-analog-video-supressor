import numpy as np
from .base import VideoClassifier


class HarmonicClassifier(VideoClassifier):
    def __init__(self, required_hits=3, threshold_db=5, logger=None):
        super().__init__("harmonic")
        self.required_hits = required_hits
        self.threshold_db = threshold_db
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

            target_freq = 15625
            sync_band = 2000

            harmonics = [1, 2, 3, 4]
            hits = 0

            for h in harmonics:
                f = h * target_freq

                mask = (np.abs(freqs - f) < sync_band) | \
                       (np.abs(freqs + f) < sync_band)

                if np.mean(power[mask]) - base_noise > self.threshold_db:
                    hits += 1

            if hits >= 3:
                votes += 1

        if self.logger:
            self.logger.log_event(
                "HARMONIC RESULT",
                "Harmonic classification result ",
                res=votes>=self.required_hits,
                freq=center_freq,
                votes=votes,
                hits=hits,
                required=self.required_hits
            )

        return {
            "confirmed": votes >= self.required_hits,
            "score": votes,
            "details": {"votes": votes}
        }