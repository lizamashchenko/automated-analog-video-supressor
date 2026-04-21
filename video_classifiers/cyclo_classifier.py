import numpy as np
from .base import VideoClassifier


class CycloClassifier(VideoClassifier):
    def __init__(
        self,
        sample_rate,
        fft_size,
        ratio_threshold=2.5,
        score_threshold=6,
        required_votes=4,
        target_freq=15625,
        harmonics=None,
        min_harmonics=2,
        max_harmonic_spread_db=15,
        logger=None
    ):
        super().__init__("cyclo")
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.ratio_threshold = ratio_threshold
        self.score_threshold = score_threshold
        self.required_votes = required_votes
        self.target_freq = target_freq
        self.harmonics = harmonics if harmonics is not None else [1, 2, 3, 4]
        self.min_harmonics = min_harmonics
        self.max_harmonic_spread_db = max_harmonic_spread_db
        self.logger = logger

    def classify(self, samples_list, sample_rate, center_freq):
        votes = 0

        for samples in samples_list:
            samples = samples[:self.fft_size]

            inst_freq = np.angle(samples[1:] * np.conj(samples[:-1]))
            inst_freq -= np.mean(inst_freq)

            N = len(inst_freq)

            if N < 128:
                if self.logger:
                    self.logger.log_event("Error in cyclostatic analysis:", "not enough samples. Received sample amount: ", N)
                continue

            x = inst_freq * np.hanning(N)

            S = np.fft.fft(x)
            freqs = np.fft.fftfreq(N, 1 / self.sample_rate)
            S_mag = np.abs(S)

            noise_floor = np.median(S_mag)

            score = 0
            ratios = []
            harmonic_db = []
            harmonics_above = 0

            for h in self.harmonics:
                f = h * self.target_freq
                idx = np.argmin(np.abs(freqs - f))

                ratio = S_mag[idx] / (noise_floor + 1e-6)
                ratios.append(ratio)
                harmonic_db.append(20 * np.log10(S_mag[idx] + 1e-12))

                if ratio > self.ratio_threshold:
                    score += ratio
                    harmonics_above += 1

            max_spread = max(
                abs(harmonic_db[j+1] - harmonic_db[j])
                for j in range(len(harmonic_db) - 1)
            )

            self.logger.log_debug_event(
                "cyclo",
                "CYCLO_SAMPLE",
                "Cyclo classification sample",
                freq = center_freq,
                ratios = [round(r, 3) for r in ratios],
                threshold = self.ratio_threshold,
                score = score,
                harmonics_above = harmonics_above,
                max_spread_db = round(max_spread, 2)
            )

            if harmonics_above >= self.min_harmonics and max_spread <= self.max_harmonic_spread_db:
                votes += 1

        confirmed = votes >= self.required_votes

        if self.logger:
            self.logger.log_debug_event(
                "cyclo",
                "CYCLO_RESULT",
                "Cyclo classification result",
                res = confirmed,
                freq = center_freq,
                votes = votes,
                required = self.required_votes
            )

        return {
            "confirmed": confirmed,
            "score": votes,
            "details": {
                "ratios": ratios,
                "noise_floor": noise_floor
            }
        }