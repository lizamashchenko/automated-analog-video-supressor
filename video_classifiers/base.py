from abc import ABC, abstractmethod
import numpy as np

class VideoClassifier(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def classify(self, samples_list, sample_rate, center_freq) -> dict:
        pass

    def compute_inst_freq(samples):
        x = np.angle(samples[1:] * np.conj(samples[:-1]))
        return x - np.mean(x)