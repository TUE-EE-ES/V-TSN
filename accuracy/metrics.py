import statistics
import threading
import time
from collections import deque
from typing import Optional

class AccuracyTracker:

    def __init__(self, maxlen=300):
        self.lock = threading.Lock()
        self.errors_ns = deque(maxlen=maxlen)
        self.delays_ns = deque(maxlen=maxlen)
        self.timestamps = deque(maxlen=maxlen)

    def add_sample(self, error_ns: int, path_delay_ns: int):
        with self.lock:
            self.errors_ns.append(error_ns)
            self.delays_ns.append(path_delay_ns)
            self.timestamps.append(time.time())

    def report(self) -> Optional[dict]:
        with self.lock:
            if len(self.errors_ns) < 3:
                return None

            errors = list(self.errors_ns)
            abs_errors = [abs(e) for e in errors]
            delays = list(self.delays_ns)

            sorted_abs = sorted(abs_errors)
            n = len(sorted_abs)
            p95_idx = int(0.95 * n)
            p99_idx = int(0.99 * n)

            return {
                "count":        n,
                "mean_ms":      statistics.mean(errors) / 1e6,
                "mean_abs_ms":  statistics.mean(abs_errors) / 1e6,
                "median_ms":    statistics.median(errors) / 1e6,
                "std_ms":       statistics.stdev(errors) / 1e6 if n > 1 else 0,
                "p95_ms":       sorted_abs[min(p95_idx, n-1)] / 1e6,
                "p99_ms":       sorted_abs[min(p99_idx, n-1)] / 1e6,
                "max_ms":       max(abs_errors) / 1e6,
                "min_ms":       min(abs_errors) / 1e6,
                "mean_delay_ms": statistics.mean(delays) / 1e6,
            }

    def get_history_ms(self, last_n=60):
        with self.lock:
            return [e / 1e6 for e in list(self.errors_ns)[-last_n:]]

    def get_last_error_ms(self) -> Optional[float]:
        with self.lock:
            if self.errors_ns:
                return self.errors_ns[-1] / 1e6
            return None
