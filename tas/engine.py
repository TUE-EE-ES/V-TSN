import threading
import time
import logging
from typing import List, Dict
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

NUM_TC   = 4
TC_NAMES = {0: "Best Effort", 1: "Background",
            2: "Excellent Effort", 3: "Time Critical"}

DEFAULT_GCL      = [
    {"gates": 0b1000, "duration_us": 1000},
    {"gates": 0b0111, "duration_us": 9000},
]
DEFAULT_CYCLE_US = 10000

def _busy_wait_until(target: float):
    while True:
        gap = target - time.perf_counter()
        if gap <= 0:
            break
        if gap > 0.0002:
            time.sleep(gap - 0.0001)
        else:
            while time.perf_counter() < target:
                pass
            break

@dataclass
class GCLEntry:
    gates:       int
    duration_us: int

    def to_dict(self):
        return {"gates": self.gates, "duration_us": self.duration_us}

    @classmethod
    def from_dict(cls, d):
        return cls(gates=int(d["gates"]), duration_us=int(d["duration_us"]))

@dataclass
class TASConfig:
    enabled:        bool           = True
    cycle_us:       int            = DEFAULT_CYCLE_US
    gcl:            List[GCLEntry] = field(default_factory=lambda: [
        GCLEntry.from_dict(e) for e in DEFAULT_GCL
    ])
    base_time_ns:   int            = 0
    port_speed_bps: int            = 0

    def total_duration_us(self) -> int:
        return sum(e.duration_us for e in self.gcl)

    def validate(self):
        if not self.gcl:
            return False, "GCL is empty"
        total = self.total_duration_us()
        if total != self.cycle_us:
            return False, f"GCL total {total}µs ≠ cycle {self.cycle_us}µs"
        for i, e in enumerate(self.gcl):
            if e.duration_us <= 0:
                return False, f"Entry {i}: duration must be > 0"
            if not (0 <= e.gates <= 0b1111):
                return False, f"Entry {i}: gates must be 0–15"
        return True, "ok"

    def to_dict(self):
        d = {
            "enabled":      self.enabled,
            "cycle_us":     self.cycle_us,
            "gcl":          [e.to_dict() for e in self.gcl],
            "base_time_ns": self.base_time_ns,
        }
        if self.port_speed_bps > 0:
            d["port_speed_bps"] = self.port_speed_bps
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(
            enabled        = d.get("enabled", True),
            cycle_us       = int(d.get("cycle_us", DEFAULT_CYCLE_US)),
            gcl            = [GCLEntry.from_dict(e)
                              for e in d.get("gcl", DEFAULT_GCL)],
            base_time_ns   = int(d.get("base_time_ns", 0)),
            port_speed_bps = int(d.get("port_speed_bps", 0)),
        )

class TASEngine:

    def __init__(self, port_id: str, config: TASConfig, clock_fn=None):
        self.port_id   = port_id
        self.config    = config
        self._clock_fn = clock_fn or (lambda: int(time.time() * 1e9))
        self._lock     = threading.Lock()
        self._queues: Dict[int, list] = {tc: [] for tc in range(NUM_TC)}
        self._wire_queues: Dict[int, deque] = {tc: deque() for tc in range(NUM_TC)}
        self._wire_seq = 0
        self._stats    = TASStats(port_id)
        self._running  = False

    def start(self):
        self._running = True
        threading.Thread(target=self._drain_loop, daemon=True,
                         name=f"tas-drain-{self.port_id}").start()
        if self.config.port_speed_bps > 0:
            threading.Thread(target=self._wire_loop, daemon=True,
                             name=f"tas-wire-{self.port_id}").start()
        speed_str = (f"{self.config.port_speed_bps/1e6:.0f}Mbps"
                     if self.config.port_speed_bps > 0 else "no wire sim")
        logger.info("[TAS:%s] Started. Cycle=%dµs, GCL=%d entries, wire=%s",
                    self.port_id, self.config.cycle_us,
                    len(self.config.gcl), speed_str)

    def stop(self):
        self._running = False

    def update_config(self, new_config: TASConfig):
        ok, msg = new_config.validate()
        if not ok:
            raise ValueError(f"Invalid TAS config for port {self.port_id}: {msg}")
        with self._lock:
            self.config = new_config
        logger.info("[TAS:%s] Config updated. Cycle=%dµs",
                    self.port_id, new_config.cycle_us)

    def enqueue(self, tc: int, data: bytes,
                dest_ip: str, dest_port: int, send_fn):
        if not self.config.enabled:
            send_fn(data, dest_ip, dest_port)
            self._stats.record_sent(tc, queued=False)
            return

        tc = max(0, min(NUM_TC - 1, tc))
        now_ns = self._clock_fn()

        if self._is_gate_open(tc, now_ns):
            if self.config.port_speed_bps > 0:
                self._wire_queues[tc].append({
                    "data": data, "dest_ip": dest_ip,
                    "dest_port": dest_port, "send_fn": send_fn,
                    "tc": tc, "seq": self._wire_seq,
                })
                self._wire_seq += 1
                self._stats.record_sent(tc, queued=False)
            else:
                send_fn(data, dest_ip, dest_port)
                self._stats.record_sent(tc, queued=False)
        else:
            with self._lock:
                self._queues[tc].append({
                    "enqueue_ns": now_ns,
                    "data":       data,
                    "dest_ip":    dest_ip,
                    "dest_port":  dest_port,
                    "send_fn":    send_fn,
                })
            self._stats.record_queued(tc)

    def _is_gate_open(self, tc: int, now_ns: int) -> bool:
        if not self.config.gcl:
            return True
        cycle_ns  = self.config.cycle_us * 1000
        offset_ns = (now_ns - self.config.base_time_ns) % cycle_ns
        pos = 0
        for entry in self.config.gcl:
            w = entry.duration_us * 1000
            if pos <= offset_ns < pos + w:
                return bool(entry.gates & (1 << tc))
            pos += w
        return False

    def _drain_loop(self):
        while self._running:
            now_ns     = self._clock_fn()
            max_age_ns = self.config.cycle_us * 1000 * 3
            use_wire   = self.config.port_speed_bps > 0

            with self._lock:
                ready = []
                for tc in range(NUM_TC):
                    q = self._queues[tc]
                    if not q:
                        continue
                    gate_open = self._is_gate_open(tc, now_ns)
                    remaining = []
                    for item in q:
                        age = now_ns - item["enqueue_ns"]
                        if age > max_age_ns:
                            self._stats.record_dropped(tc)
                            continue
                        if gate_open:
                            ready.append((item["enqueue_ns"], tc, item))
                        else:
                            remaining.append(item)
                    self._queues[tc] = remaining

                ready.sort(key=lambda x: x[0])

            for _, tc, item in ready:
                if use_wire:
                    self._wire_queues[tc].append({
                        "data": item["data"], "dest_ip": item["dest_ip"],
                        "dest_port": item["dest_port"],
                        "send_fn": item["send_fn"], "tc": tc,
                        "seq": self._wire_seq,
                    })
                    self._wire_seq += 1
                else:
                    try:
                        item["send_fn"](item["data"],
                                        item["dest_ip"],
                                        item["dest_port"])
                    except Exception as e:
                        logger.warning("[TAS:%s] Send error: %s",
                                       self.port_id, e)
                self._stats.record_sent(tc, queued=True)

            time.sleep(0.0001)

    def _wire_loop(self):
        port_speed = self.config.port_speed_bps
        while self._running:
            now_ns = self._clock_fn()
            best_item = None
            best_tc   = -1
            best_seq  = float('inf')
            for tc in range(NUM_TC):
                q = self._wire_queues[tc]
                if q and self._is_gate_open(tc, now_ns):
                    if q[0]["seq"] < best_seq:
                        best_seq  = q[0]["seq"]
                        best_tc   = tc
                        best_item = q[0]
            if best_item is not None:
                self._wire_queues[best_tc].popleft()
                pkt_bits  = len(best_item["data"]) * 8
                tx_time_s = pkt_bits / port_speed
                _busy_wait_until(time.perf_counter() + tx_time_s)
                try:
                    best_item["send_fn"](best_item["data"],
                                         best_item["dest_ip"],
                                         best_item["dest_port"])
                except Exception as e:
                    logger.warning("[TAS:%s] Wire send error: %s",
                                   self.port_id, e)
            else:
                time.sleep(0.0001)

    def get_gate_state(self) -> Dict:
        now_ns = self._clock_fn()
        return {
            tc: {
                "name":   TC_NAMES[tc],
                "open":   self._is_gate_open(tc, now_ns),
                "queued": len(self._queues.get(tc, [])),
            }
            for tc in range(NUM_TC)
        }

    def get_cycle_position_us(self) -> float:
        now_ns   = self._clock_fn()
        cycle_ns = self.config.cycle_us * 1000
        return ((now_ns - self.config.base_time_ns) % cycle_ns) / 1000.0

    def get_stats(self) -> Dict:
        return self._stats.snapshot()

class TASStats:
    def __init__(self, port_id: str):
        self.port_id       = port_id
        self._lock         = threading.Lock()
        self.sent          = {tc: 0 for tc in range(NUM_TC)}
        self.queued        = {tc: 0 for tc in range(NUM_TC)}
        self.dropped       = {tc: 0 for tc in range(NUM_TC)}
        self.sent_immediate= {tc: 0 for tc in range(NUM_TC)}

    def record_sent(self, tc: int, queued: bool):
        with self._lock:
            self.sent[tc] = self.sent.get(tc, 0) + 1
            if not queued:
                self.sent_immediate[tc] = self.sent_immediate.get(tc, 0) + 1

    def record_queued(self, tc: int):
        with self._lock:
            self.queued[tc] = self.queued.get(tc, 0) + 1

    def record_dropped(self, tc: int):
        with self._lock:
            self.dropped[tc] = self.dropped.get(tc, 0) + 1

    def snapshot(self) -> Dict:
        with self._lock:
            return {
                "port_id":       self.port_id,
                "sent":          dict(self.sent),
                "queued":        dict(self.queued),
                "dropped":       dict(self.dropped),
                "sent_immediate":dict(self.sent_immediate),
            }
