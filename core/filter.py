import collections
import statistics

class DelayFilter:
    def __init__(self, window=32):
        self.window = window
        self.samples = collections.deque(maxlen=window)

    def add(self, sample_ns: int):
        if sample_ns > 0:
            self.samples.append(sample_ns)

    def get_minimum(self) -> int:
        if not self.samples:
            return 0
        return min(self.samples)

    def get_median(self) -> int:
        if not self.samples:
            return 0
        return int(statistics.median(self.samples))

    def get_best(self) -> int:
        if not self.samples:
            return 0
        return int(0.6 * self.get_minimum() + 0.4 * self.get_median())

    def is_ready(self) -> bool:
        return len(self.samples) >= min(8, self.window)

    def reset(self):
        self.samples.clear()

    def __len__(self):
        return len(self.samples)
