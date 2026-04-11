# utils/sdr_reader.py

import threading
from queue import Queue, Full
import numpy as np


class SDRReader:
    def __init__(self, device, buffer_size, queue_size=100, sample_size=4096, logger=None):
        self.device = device
        self.buffer_size = buffer_size
        self.sample_size = sample_size
        self.queue = Queue(maxsize=queue_size)
        self.logger = logger

        self.running = False
        self.thread = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def flush(self):
        """Discard all samples currently in the queue (call after device.tune())."""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except Exception:
                break

    def _run(self):
        buff = np.empty(self.buffer_size, np.complex64)

        while self.running:
            sr = self.device.read(buff)

            if sr.ret <= 0:
                if self.logger:
                    self.logger.log_event(
                        "SDR_READ_ERROR",
                        "readStream failed",
                        code=sr.ret
                    )
                continue

            if np.all(buff == 0):
                if self.logger:
                    self.logger.log_event(
                        "ZERO_BUFFER",
                        "All samples are zero"
                    )
                continue

            try:
                self.queue.put(buff.copy(), timeout=0.1)
            except Full:
                if self.logger:
                    self.logger.log_event(
                        "QUEUE_FULL",
                        "Dropping samples"
                    )

    def get_samples(self, timeout=0.5):
        try:
            samples = self.queue.get(timeout=timeout)

            if samples is None or len(samples) < self.sample_size:
                return None

            samples = samples[:self.sample_size]

            if np.all(samples == 0):
                return None

            return samples

        except:
            return None