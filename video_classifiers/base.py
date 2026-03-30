class VideoClassifier:
    def __init__(self, name):
        self.name = name

    def classify(self, samples_list, sample_rate, center_freq):
        """
        Returns:
        {
            "confirmed": bool,
            "score": float/int,
            "details": dict
        }
        """
        raise NotImplementedError