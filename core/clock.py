import time
import threading

class LocalClock:
    def __init__(self):
        self.offset_ns = 0
        self.lock = threading.Lock()
        self.kp = 0.7
        self.ki = 0.3
        self._integral = 0.0
        self._last_offset = 0
        self.offset_history = []
        self.max_history = 300

    def now_ns(self):
        raw = int(time.time() * 1e9)
        with self.lock:
            return raw + self.offset_ns

    def now_ms(self):
        return self.now_ns() / 1e6

    def adjust(self, offset_ns: int):
        with self.lock:
            self._integral += offset_ns * self.ki
            correction = int(offset_ns * self.kp + self._integral)
            max_step = 10_000_000
            correction = max(-max_step, min(max_step, correction))
            self.offset_ns -= correction
            self._last_offset = offset_ns
            self.offset_history.append(offset_ns)
            if len(self.offset_history) > self.max_history:
                self.offset_history.pop(0)

    def get_offset_ms(self):
        with self.lock:
            return self._last_offset / 1e6

    def get_history_ms(self):
        with self.lock:
            return [x / 1e6 for x in self.offset_history[-60:]]

    def reset(self):
        with self.lock:
            self.offset_ns = 0
            self._integral = 0.0
            self._last_offset = 0
            self.offset_history = []
