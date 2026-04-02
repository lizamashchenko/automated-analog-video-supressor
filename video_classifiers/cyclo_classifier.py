import numpy as np
from .base import VideoClassifier 

class CycloClassifier (VideoClassifier):
    def __init__(
        self,
        sample_rate,
        fft_size,
        ratio_threshold=2.5,
        score_threshold=6,
        required_votes=3,
        logger=None
    ):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.ratio_threshold = ratio_threshold
        self.score_threshold = score_threshold
        self.required_votes = required_votes
        self.logger = logger
        self.name = "cyclo"

        self.target_freq = 15625
        self.harmonics = [1, 2, 3, 4]

    def classify(self, samples_list, sample_rate, center_freq):
        votes = 0

        for i, samples in enumerate(samples_list):
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

            noise_floor = np.mean(S_mag)

            score = 0
            ratios = []

            for h in self.harmonics:
                f = h * self.target_freq
                idx = np.argmin(np.abs(freqs - f))

                ratio = S_mag[idx] / (noise_floor + 1e-6)
                ratios.append(ratio)

                if ratio > self.ratio_threshold:
                    score += ratio

            if ratios[0] >= self.ratio_threshold:
                votes += 1

        confirmed = votes >= self.required_votes

        if self.logger:
            self.logger.log_event(
                "CYCLO_RESULT",
                "Cyclo classification result",
                res=confirmed,
                freq=center_freq,
                votes=votes,
                required=self.required_votes
            )

        return {
            "confirmed": confirmed,
            "score": votes,
            "details": {
                "ratios": ratios,
                "noise_floor": noise_floor
            }
        }