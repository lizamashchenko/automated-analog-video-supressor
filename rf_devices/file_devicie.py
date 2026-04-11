import numpy as np
import time
import csv
from collections import defaultdict


class FakeResult:
    def __init__(self, ret):
        self.ret = ret


class FileDevice:
    def __init__(self, filepath, metadata_path, sample_rate, loop=True):
        self.samples = np.memmap(filepath, dtype=np.complex64, mode='r')
        self.sample_rate = sample_rate
        self.loop = loop

        self.chunks = defaultdict(list)
        with open(metadata_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                freq = float(row["center_freq"])
                sample_off = int(row["offset_bytes"]) // 8
                n = int(row["num_samples"])
                self.chunks[freq].append((sample_off, n))
        self.ptr = 0
        self.loop = loop

        self.start_time = time.time()
        self.samples_served = 0

    def _load_iq(self, filepath):
        raw = np.fromfile(filepath, dtype=np.complex64)
        iq = raw.reshape(-1, 2)
        iq = iq[:, 0].astype(np.float32) + 1j * iq[:, 1].astype(np.float32)
        iq /= 128.0
        return iq.astype(np.complex64)

    def tune(self, freq):
        pass

    def read(self, buff):
        n = len(buff)

        expected_time = self.samples_served / self.sample_rate
        real_time = time.time() - self.start_time

        if expected_time > real_time:
            time.sleep(expected_time - real_time)

        if self.ptr + n > len(self.samples):
            if not self.loop:
                return FakeResult(0)
            self.ptr = 0

        chunk = self.samples[self.ptr:self.ptr + n]
        buff[:len(chunk)] = chunk

        self.ptr += n
        self.samples_served += n

        return FakeResult(len(chunk))