import numpy as np

# A class describing plateau detection logic. Evaluates if samples contain a plateau, or are noise

class PlateauDetector:
    # init function
    def __init__(
        self,
        sample_rate,
        fft_size,
        wide_sampling_num,
        freq_tolerance=2e6,
        above_noise_threshold=0.5,
        edge_drop_level=0.1,
        min_lobe_size=0.2,
        lobe_merge_gap=3.0,
        min_video_width=2.7,
        max_video_width=10.0,
        plateau_required_ratio=0.3,
        logger=None
    ):
        self.sample_rate = sample_rate
        self.fft_size = fft_size
        self.freq_tolerance = freq_tolerance
        self.wide_sampling_num = wide_sampling_num

        self.mhz_per_bin = sample_rate / fft_size / 1e6
        self.lobe_merge_bins = int(lobe_merge_gap / self.mhz_per_bin)

        self.above_noise_threshold = above_noise_threshold
        self.edge_drop_level = edge_drop_level
        self.min_lobe_size = min_lobe_size
        self.min_video_width = min_video_width
        self.max_video_width = max_video_width

        self.plateau_required_hits = int(wide_sampling_num * plateau_required_ratio)

        self.logger = logger

    # high-level detection function
    def detect(self, power, center_freq):
        freqs = np.linspace(
            center_freq - self.sample_rate / 2,
            center_freq + self.sample_rate / 2,
            self.fft_size
        )

        clusters = self._find_clusters(power, center_freq)
        return self._extract_plateau(clusters, freqs)

    # high-level function which validates a plateau as "strong" enough
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

    # glabal across runs map update
    def update_map(self, plateau_map, plateau):
        key = int(plateau["center_freq"] / self.freq_tolerance)

        if key not in plateau_map:
            plateau_map[key] = []

        plateau_map[key].extend(plateau["samples"])
        plateau_map[key] = plateau_map[key][-5:]

# =============== INNER LOOP ===================

    # function which returns clusters
    def _find_clusters(self, power, center_freq):
        # smooth spectrum to remove noise
        smoothed = np.convolve(power, np.ones(3)/3, mode='same')
        noise_floor = np.median(smoothed)

        # find peaks above noise floor
        above = smoothed[1:-1] - (noise_floor + self.above_noise_threshold)
        peak_mask = (smoothed[1:-1] > smoothed[:-2]) & (smoothed[1:-1] > smoothed[2:]) & (above > 0)
        peak_indices = np.where(peak_mask)[0] + 1
        max_above = float(np.max(above)) if len(above) > 0 else 0.0

        # expand each peak to lobes
        lobes = self._expand_to_lobes(smoothed, peak_indices, noise_floor)
        
        # merge nearby lobes in one cluster
        merged, rejected_merged = self._merge_lobes(lobes)

        # log results
        if self.logger:
            max_lobe_mhz = 0.0
            if lobes:
                max_lobe_mhz = max((r - l + 1) * self.mhz_per_bin for l, r in lobes)
            max_merged_mhz = 0.0
            if rejected_merged:
                max_merged_mhz = max(rejected_merged)
            if merged:
                max_merged_mhz = max(max_merged_mhz, max(bw for _, _, bw in merged))

            self.logger.log_debug_event(
                "plateau",
                "CLUSTER_DEBUG",
                "Cluster detection stats",
                freq_mhz=round(center_freq / 1e6, 1),
                noise=round(float(noise_floor), 2),
                max_above_noise=round(max_above, 2),
                thresh=self.above_noise_threshold,
                peaks=len(peak_indices),
                lobes=len(lobes),
                max_lobe_mhz=round(max_lobe_mhz, 2),
                merged_total=len(merged) + len(rejected_merged),
                max_merged_mhz=round(max_merged_mhz, 2),
                clusters=len(merged),
                width_range=f"{self.min_video_width}-{self.max_video_width}",
            )

        return merged

    def _expand_to_lobes(self, data, peaks, noise):
        edge_threshold = noise + self.edge_drop_level
        lobes = []

        # determine left-most and right-most edges above noise
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
    
    # merge lobes into clusters
    def _merge_lobes(self, lobes):
        clusters = []
        rejected_widths = []

        if not lobes:
            return clusters, rejected_widths

        lobes.sort()
        cur_left, cur_right = lobes[0]

        # iterate lobes
        for left, right in lobes[1:]:
            if left - cur_right <= self.lobe_merge_bins:
                # extend
                cur_right = max(cur_right, right)
            else:
                bw_bins = cur_right - cur_left + 1
                bw_mhz = bw_bins * self.mhz_per_bin

                # check eligibility
                if bw_mhz >= self.min_video_width and bw_mhz <= self.max_video_width:
                    clusters.append((cur_left, cur_right, bw_mhz))
                else:
                    rejected_widths.append(bw_mhz)
                # update 
                cur_left, cur_right = left, right

        # check last
        bw_bins = cur_right - cur_left + 1
        bw_mhz = bw_bins * self.mhz_per_bin

        if bw_mhz >= self.min_video_width and bw_mhz <= self.max_video_width:
            clusters.append((cur_left, cur_right, bw_mhz))
        else:
            rejected_widths.append(bw_mhz)

        return clusters, rejected_widths

    # calculate plateau parameters
    def _extract_plateau(self, clusters, freqs):
        if not clusters:
            return None

        left, right, bw = max(clusters, key=lambda x: x[2])
        center_bin = (left + right) // 2

        if center_bin < 0 or center_bin >= len(freqs):
            if self.logger:
                self.logger.log_event(
                    "INVALID_BIN",
                    "Center bin out of bounds",
                    level=1,
                    bin=center_bin,
                    size=len(freqs)
                )
            return None

        return {
            "center_freq": freqs[center_bin],
            "bandwidth": bw,
            "bin": center_bin
        }