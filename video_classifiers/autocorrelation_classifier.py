import numpy as np


class AutocorrClassifier:
    def __init__(
        self,
        sample_rate,
        decimation=1,
        line_freq=15625,       
        lag_tolerance=0.1,     
        peak_threshold=0.18,
        required_votes=2,
        logger=None
    ):
        self.sample_rate = sample_rate
        self.decimation = decimation
        self.fs_decim = sample_rate / decimation
        self.line_freq = line_freq
        self.lag_tolerance = lag_tolerance
        self.peak_threshold = peak_threshold
        self.required_votes = required_votes
        self.logger = logger
        self.name = "AutocorrClassifier"

    def classify(self, samples_list, sample_rate, center_freq):
        votes = 0
        peaks = []

        for iq in samples_list:
            peak = self._autocorr_peak(iq)
            peaks.append(peak)

            confirmed = peak is not None and peak > self.peak_threshold
            if confirmed:
                votes += 1

            if self.logger:
                self.logger.log_debug_event(
                    "autocorr",
                    "AUTOCORR_SAMPLE",
                    "Per-buffer autocorr result",
                    freq=center_freq,
                    peak=float(peak) if peak is not None else -1.0,
                    confirmed=confirmed,
                )

        total = len(samples_list)
        score = votes / total if total > 0 else 0.0
        confirmed = votes >= self.required_votes

        if self.logger:
            self.logger.log_debug_event(
                "autocorr",
                "AUTOCORR_RESULT",
                f"{self.name} classification",
                freq=center_freq,
                votes=votes,
                total=total,
                score=score,
                confirmed=confirmed,
            )

        return {
            "score": score,
            "confirmed": confirmed,
            "details": {
                "votes": votes,
                "peaks": peaks
            }
        }

    def _autocorr_peak(self, iq):
        inst_freq = np.angle(iq[1:] * np.conj(iq[:-1]))
        inst_freq -= np.mean(inst_freq)

        from scipy.signal import decimate
        q = int(self.sample_rate // 1_000_000)
        if q > 1:
            inst_freq = decimate(inst_freq, q, ftype='fir', zero_phase=True)
        fs_eff = self.sample_rate / q

        n = len(inst_freq)
        if n < 2:
            return None

        corr = np.correlate(inst_freq, inst_freq, mode='full')
        corr = corr[len(corr) // 2:]

        if corr[0] < 1e-12:
            return None
        corr = corr / corr[0]

        target_lag = int(round(fs_eff / self.line_freq))
        tol = max(2, int(self.lag_tolerance * target_lag))
        lag_lo = max(1, target_lag - tol)
        lag_hi = min(len(corr) - 1, target_lag + tol)

        if lag_hi <= lag_lo:
            return None

        region = corr[lag_lo:lag_hi + 1]
        baseline = np.median(corr[1:lag_lo]) if lag_lo > 10 else 0.0
        return float(np.max(region) - baseline)