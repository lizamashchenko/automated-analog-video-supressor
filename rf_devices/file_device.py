import numpy as np
import csv
from collections import defaultdict

class FakeResult:
    def __init__(self, ret):
        self.ret = ret

# a file reader class imitating a real SDR from the recorded data
class FileDevice:
    def __init__(self, filepath, metadata_path, sample_rate, loop=True):
        # memap file, as they are quite big
        self.samples = np.memmap(filepath, dtype=np.complex64, mode='r')
        self.sample_rate = sample_rate
        self.loop = loop

        self.chunks = defaultdict(list)
        # load recording metadata
        with open(metadata_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                freq = float(row["center_freq"])
                sample_off = int(row["offset_bytes"]) // 8
                n = int(row["num_samples"])
                self.chunks[freq].append((sample_off, n))

        self.current_freq = None
        self.chunk_idx = 0

    def tune(self, freq):
        self.current_freq = freq
        self.chunk_idx = 0

    def close(self):
        pass
    
    # retrieve samples from file
    def read(self, buff):
        if self.current_freq is None or self.current_freq not in self.chunks:
            return FakeResult(0)

        freq_chunks = self.chunks[self.current_freq]

        if self.chunk_idx >= len(freq_chunks):
            if not self.loop:
                return FakeResult(0)
            self.chunk_idx = 0

        sample_off, n = freq_chunks[self.chunk_idx]
        self.chunk_idx += 1

        n = min(n, len(buff))
        chunk = self.samples[sample_off:sample_off + n]
        buff[:len(chunk)] = chunk

        return FakeResult(len(chunk))
