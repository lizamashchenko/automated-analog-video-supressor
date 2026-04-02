from .base import VideoClassifier
import numpy as np

FFT_SIZE = 4096 
DEMOD_REQUIRED_HITS = 3


class AutocorrClassifier(VideoClassifier):
    def __init__(self, sample_rate, decimation=10, line_freq=15625, threshold=0.1):
        self.sample_rate = sample_rate
        self.decimation = decimation
        self.fs_decim = sample_rate / decimation
        self.line_freq = line_freq
        self.threshold = threshold

        self.name = "autocorr"

    def classify(self, samples_list, sample_rate, center_freq):
        peaks = []

        for i, iq in enumerate(samples_list):
            iq = iq[::self.decimation]

            inst_freq = np.angle(iq[1:] * np.conj(iq[:-1]))
            inst_freq -= np.mean(inst_freq)

            if len(inst_freq) < FFT_SIZE:
                continue

            x = inst_freq[:FFT_SIZE]

            corr = np.correlate(x, x, mode='full')
            corr = corr[len(corr)//2:]
            corr /= np.max(corr) + 1e-6

            target_lag = int(self.fs_decim / self.line_freq)
            tol = int(0.1 * target_lag)

            if target_lag + tol >= len(corr):
                continue

            region = corr[target_lag - tol : target_lag + tol]
            peak = np.max(region)
            peaks.append(peak)


        if not peaks:
            return {
                "confirmed": False,
                "score": 0,
                "details": {
                    "peaks_len": len(peaks)
                }
            }

        avg_peak = np.mean(peaks)
        votes = sum(p > self.threshold for p in peaks)

        return {
            "confirmed": votes >= DEMOD_REQUIRED_HITS,
            "score": votes,
            "details": {
                "avg_peak": avg_peak,
                "peaks": peaks,
                "target_lag": target_lag
            }
        }