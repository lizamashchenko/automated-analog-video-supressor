from abc import ABC, abstractmethod


class VideoClassifier(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def classify(self, samples_list, sample_rate, center_freq) -> dict:
        pass
