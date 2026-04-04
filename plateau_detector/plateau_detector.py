import numpy as np


class PlateauDetector:
    def __init__(
        self,
        sample_rate,
        fft_size,
        wide_sampling_num,
        freq_tolerance=2e6,
        above_noise_threshold=0.3,
        edge_drop_level=0.1,
        min_lobe_size=0.1,
        lobe_merge_gap=10.0,
        min_video_width=2.0,
        max_video_width=10,
        plateau_required_ratio=0.3,
        logger=None
    ):
        # Core params
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.freq_tolerance = freq_tolerance
        self.wide_sampling_num = wide_sampling_num

        # Derived
        self.mhz_per_bin = sample_rate / fft_size / 1e6
        self.lobe_merge_bins = int(lobe_merge_gap / self.mhz_per_bin)

        # Thresholds
        self.above_noise_threshold = above_noise_threshold
        self.edge_drop_level = edge_drop_level
        self.min_lobe_size = min_lobe_size
        self.min_video_width = min_video_width
        self.max_video_width = max_video_width

        self.plateau_required_hits = int(wide_sampling_num * plateau_required_ratio)

        # Optional logger
        self.logger = logger

    # -----------------------------
    # Public API
    # -----------------------------
    def detect(self, power, center_freq):
        freqs = np.linspace(
            center_freq - self.sample_rate / 2,
            center_freq + self.sample_rate / 2,
            self.fft_size
        )

        clusters = self._find_clusters(power)
        return self._extract_plateau(clusters, freqs)

    def validate(self, detections):
        if len(detections) < self.plateau_required_hits:
            return None

        freqs = [d[1]["center_freq"] for d in detections]
        bws = [d[1]["bandwidth"] for d in detections]

        return {
            "center_freq": np.median(freqs),
            "bandwidth": np.max(bws),
            "samples": [d[0] for d in detections]
        }

    def update_map(self, plateau_map, plateau):
        key = int(plateau["center_freq"] / self.freq_tolerance)

        if key not in plateau_map:
            plateau_map[key] = []

        plateau_map[key].extend(plateau["samples"])
        plateau_map[key] = plateau_map[key][-5:]

    # -----------------------------
    # Internal pipeline
    # -----------------------------
    def _find_clusters(self, power):
        smoothed = np.convolve(power, np.ones(3)/3, mode='same')
        noise_floor = np.median(smoothed)

        peak_indices = np.where(
            (smoothed[1:-1] > smoothed[:-2]) &
            (smoothed[1:-1] > smoothed[2:]) &
            (smoothed[1:-1] > noise_floor + self.above_noise_threshold)
        )[0] + 1

        lobes = self._expand_to_lobes(smoothed, peak_indices, noise_floor)
        clusters = self._merge_lobes(lobes)

        if self.logger:
            self.logger.log_event(
                "CLUSTER_DEBUG",
                "Cluster detection stats",
                noise=float(noise_floor),
                peaks=len(peak_indices),
                lobes=len(lobes),
                clusters=len(clusters)
            )

        return clusters

    def _expand_to_lobes(self, data, peaks, noise):
        edge_threshold = noise + self.edge_drop_level
        lobes = []

        for peak_idx in peaks:
            left = peak_idx
            while left > 0 and data[left] > edge_threshold:
                left -= 1

            right = peak_idx
            while right < len(data) - 1 and data[right] > edge_threshold:
                right += 1

            bw_bins = right - left + 1
            bw_mhz = bw_bins * self.mhz_per_bin

            if bw_mhz >= self.min_lobe_size:
                lobes.append((left, right))

        return lobes

    def _merge_lobes(self, lobes):
        clusters = []

        if not lobes:
            return clusters

        lobes.sort()
        cur_left, cur_right = lobes[0]

        for left, right in lobes[1:]:
            if left - cur_right <= self.lobe_merge_bins:
                cur_right = max(cur_right, right)
            else:
                # save previous
                bw_bins = cur_right - cur_left + 1
                bw_mhz = bw_bins * self.mhz_per_bin

                if bw_mhz >= self.min_video_width:
                    clusters.append((cur_left, cur_right, bw_mhz))

                cur_left, cur_right = left, right

        # last cluster
        bw_bins = cur_right - cur_left + 1
        bw_mhz = bw_bins * self.mhz_per_bin

        if bw_mhz >= self.min_video_width:
            clusters.append((cur_left, cur_right, bw_mhz))

        return clusters

    def _extract_plateau(self, clusters, freqs):
        if not clusters:
            return None

        left, right, bw = max(clusters, key=lambda x: x[2])
        center_bin = (left + right) // 2

        # safety check
        if center_bin < 0 or center_bin >= len(freqs):
            if self.logger:
                self.logger.log_event(
                    "INVALID_BIN",
                    "Center bin out of bounds",
                    bin=center_bin,
                    size=len(freqs)
                )
            return None

        return {
            "center_freq": freqs[center_bin],
            "bandwidth": bw,
            "bin": center_bin
        }