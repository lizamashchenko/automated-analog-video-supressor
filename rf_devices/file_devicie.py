import numpy as np
import time
import csv


class FakeResult:
    def __init__(self, ret):
        self.ret = ret


class FileDevice:
    def __init__(self, iq_path, meta_path, sample_rate):
        self.iq_path = iq_path
        self.meta_path = meta_path
        self.sample_rate = sample_rate

        self.file = open(self.iq_path, "rb")

        self.freq_map = self._load_metadata()

        self.current_chunks = []
        self.chunk_idx = 0
        self.ptr_in_chunk = 0

        self.start_time = time.time()
        self.samples_served = 0

    def _load_metadata(self):
        freq_map = {}

        with open(self.meta_path, "r") as f:
            reader = csv.DictReader(f)

            for row in reader:
                freq = float(row["center_freq"])
                offset = int(row["offset_bytes"])
                num_samples = int(row["num_samples"])

                if freq not in freq_map:
                    freq_map[freq] = []

                freq_map[freq].append((offset, num_samples))

        return freq_map

    def tune(self, freq):
        available = np.array(list(self.freq_map.keys()))
        idx = np.argmin(np.abs(available - freq))
        closest_freq = available[idx]

        self.current_chunks = self.freq_map[closest_freq]
        self.chunk_idx = 0
        self.ptr_in_chunk = 0

        self.start_time = time.time()
        self.samples_served = 0

        self.settling_until = time.time() + 0.02

    def _read_chunk(self, offset, num_samples):
        self.file.seek(offset)
        raw = np.fromfile(self.file, dtype=np.complex64, count=num_samples)
        return raw

    def read(self, buff):
        n = len(buff)

        expected_time = self.samples_served / self.sample_rate
        real_time = time.time() - self.start_time

        if expected_time > real_time:
            time.sleep(expected_time - real_time)

        if hasattr(self, "settling_until") and time.time() < self.settling_until:
            buff[:] = (np.random.randn(n) + 1j*np.random.randn(n)) * 0.05
            self.samples_served += n
            return FakeResult(n)

        if not self.current_chunks:
            return FakeResult(0)

        out = np.empty(n, dtype=np.complex64)
        filled = 0

        while filled < n:
            offset, num_samples = self.current_chunks[self.chunk_idx]

            chunk = self._read_chunk(offset, num_samples)

            remaining = chunk[self.ptr_in_chunk:]

            take = min(len(remaining), n - filled)
            out[filled:filled+take] = remaining[:take]

            filled += take
            self.ptr_in_chunk += take

            if self.ptr_in_chunk >= len(chunk):
                self.chunk_idx = (self.chunk_idx + 1) % len(self.current_chunks)
                self.ptr_in_chunk = 0

        buff[:] = out
        self.samples_served += n

        return FakeResult(n)