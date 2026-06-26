import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Dict

logger = logging.getLogger(__name__)

NUM_TC             = 4
MAX_QUEUE_DEPTH    = 5000
DEFAULT_PORT_SPEED = 100_000_000

DEFAULT_CBS_TC = {
    0: {"enabled": False, "idle_slope_bps": 0,          "max_credit_bytes": 0},
    1: {"enabled": True,  "idle_slope_bps": 10_000_000, "max_credit_bytes": 12_500},
    2: {"enabled": True,  "idle_slope_bps": 25_000_000, "max_credit_bytes": 12_500},
    3: {"enabled": False, "idle_slope_bps": 0,          "max_credit_bytes": 0},
}

@dataclass
class CBSTCConfig:
    enabled:          bool = False
    idle_slope_bps:   int  = 0
    max_credit_bytes: int  = 12_500

    def send_slope_bps(self, port_speed_bps):
        return self.idle_slope_bps - port_speed_bps

    def to_dict(self):
        return {"enabled": self.enabled,
                "idle_slope_bps": self.idle_slope_bps,
                "max_credit_bytes": self.max_credit_bytes}

    @classmethod
    def from_dict(cls, d):
        return cls(enabled=d.get("enabled", False),
                   idle_slope_bps=int(d.get("idle_slope_bps", 0)),
                   max_credit_bytes=int(d.get("max_credit_bytes", 12_500)))

@dataclass
class CBSConfig:
    enabled:        bool                   = True
    port_speed_bps: int                    = DEFAULT_PORT_SPEED
    tc_configs:     Dict[int, CBSTCConfig] = field(
        default_factory=lambda: {
            tc: CBSTCConfig.from_dict(DEFAULT_CBS_TC[tc])
            for tc in range(NUM_TC)
        })

    def to_dict(self):
        return {"enabled": self.enabled,
                "port_speed_bps": self.port_speed_bps,
                "tc_configs": {str(tc): cfg.to_dict()
                               for tc, cfg in self.tc_configs.items()}}

    @classmethod
    def from_dict(cls, d):
        tc_raw = d.get("tc_configs", {})
        tc_configs = {}
        for tc in range(NUM_TC):
            key = str(tc)
            tc_configs[tc] = CBSTCConfig.from_dict(
                tc_raw[key] if key in tc_raw else DEFAULT_CBS_TC[tc])
        return cls(enabled=d.get("enabled", True),
                   port_speed_bps=int(d.get("port_speed_bps", DEFAULT_PORT_SPEED)),
                   tc_configs=tc_configs)

    def validate(self):
        total = sum(cfg.idle_slope_bps for cfg in self.tc_configs.values()
                    if cfg.enabled)
        if total >= self.port_speed_bps:
            return False, f"Total idleSlope {total} >= portSpeed {self.port_speed_bps}"
        return True, "ok"

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

class CBSEngine:

    def __init__(self, port_id: str, config: CBSConfig, clock_fn=None):
        self.port_id  = port_id
        self.config   = config
        self._lock    = threading.Lock()
        self._running = False
        self._event   = threading.Event()

        self._queues:  Dict[int, list]  = {tc: [] for tc in range(NUM_TC)}
        self._credits: Dict[int, float] = {tc: 0.0 for tc in range(NUM_TC)}
        self._last_t:  Dict[int, float] = {tc: time.perf_counter()
                                            for tc in range(NUM_TC)}
        self._stats   = CBSStats(port_id)

    def start(self):
        self._running = True
        threading.Thread(target=self._drain_loop, daemon=True,
                         name=f"cbs-drain-{self.port_id}").start()
        enabled = [tc for tc in range(NUM_TC)
                   if self.config.tc_configs.get(tc, CBSTCConfig()).enabled]
        logger.info("[CBS:%s] Started (priority drain). port=%d bps enabled TCs=%s",
                    self.port_id, self.config.port_speed_bps, enabled)

    def stop(self):
        self._running = False
        self._event.set()

    def update_config(self, new_config: CBSConfig):
        ok, msg = new_config.validate()
        if not ok:
            raise ValueError(f"Invalid CBS config: {msg}")
        with self._lock:
            self.config = new_config
        logger.info("[CBS:%s] Config updated", self.port_id)

    def check_and_send(self, tc: int, data: bytes,
                       dest_ip: str, dest_port: int, send_fn):
        tc  = max(0, min(NUM_TC - 1, tc))
        cfg = self.config.tc_configs.get(tc, CBSTCConfig())

        if not self.config.enabled or not cfg.enabled:
            send_fn(data, dest_ip, dest_port)
            self._stats.record_sent(tc, queued=False)
            return

        with self._lock:
            if len(self._queues[tc]) >= MAX_QUEUE_DEPTH:
                self._stats.record_dropped(tc)
                logger.debug("[CBS:%s] TC%d queue full — drop", self.port_id, tc)
                return
            self._queues[tc].append({
                "data":      data,
                "dest_ip":   dest_ip,
                "dest_port": dest_port,
                "send_fn":   send_fn,
            })
        self._event.set()
        self._stats.record_sent(tc, queued=True)

    def _drain_loop(self):
        port_speed   = self.config.port_speed_bps
        last_update  = time.perf_counter()
        pending_tc   = -1
        pending_drain = 0.0
        exclude_tc   = -1

        while self._running:
            self._event.wait(timeout=0.005)
            self._event.clear()

            while self._running:
                now = time.perf_counter()
                elapsed = now - last_update
                last_update = now

                selected_tc   = None
                selected_item = None
                any_queued    = False

                with self._lock:
                    if pending_tc >= 0:
                        self._credits[pending_tc] += pending_drain
                        self._credits[pending_tc] = max(
                            self._credits[pending_tc],
                            -self.config.tc_configs[pending_tc
                             ].max_credit_bytes)
                        pending_tc = -1

                    exc = exclude_tc
                    exclude_tc = -1
                    for tc in range(NUM_TC):
                        if tc == exc:
                            continue
                        cfg = self.config.tc_configs.get(tc, CBSTCConfig())
                        if not cfg.enabled:
                            continue
                        if not self._queues[tc]:
                            if self._credits[tc] > 0:
                                self._credits[tc] = 0.0
                            elif self._credits[tc] < 0:
                                self._credits[tc] = min(
                                    self._credits[tc]
                                    + cfg.idle_slope_bps * elapsed,
                                    0.0)
                        else:
                            if self._credits[tc] < 0:
                                self._credits[tc] = min(
                                    self._credits[tc]
                                    + cfg.idle_slope_bps * elapsed,
                                    cfg.max_credit_bytes)

                    for tc in range(NUM_TC - 1, -1, -1):
                        cfg = self.config.tc_configs.get(tc, CBSTCConfig())
                        if not cfg.enabled:
                            continue
                        if self._queues[tc] and self._credits[tc] >= 0:
                            selected_tc   = tc
                            selected_item = self._queues[tc].pop(0)
                            break

                    if selected_item is None:
                        any_queued = any(
                            self._queues[t]
                            for t in range(NUM_TC)
                            if self.config.tc_configs.get(
                                t, CBSTCConfig()).enabled)

                if selected_item is not None:
                    tc  = selected_tc
                    cfg = self.config.tc_configs[tc]

                    try:
                        selected_item["send_fn"](
                            selected_item["data"],
                            selected_item["dest_ip"],
                            selected_item["dest_port"])
                    except Exception as e:
                        logger.warning("[CBS:%s] Send error: %s",
                                       self.port_id, e)

                    pkt_bits  = len(selected_item["data"]) * 8
                    tx_time_s = pkt_bits / port_speed
                    _busy_wait_until(time.perf_counter() + tx_time_s)

                    pending_tc    = tc
                    pending_drain = cfg.send_slope_bps(port_speed) \
                                    * tx_time_s
                    exclude_tc    = tc

                else:
                    if not any_queued:
                        break
                    time.sleep(0.0001)

    def get_credit_info(self) -> Dict:
        with self._lock:
            return {tc: {
                "tc":             tc,
                "credit_bytes":   round(self._credits.get(tc, 0.0), 1),
                "max_credit":     self.config.tc_configs.get(
                                      tc, CBSTCConfig()).max_credit_bytes,
                "idle_slope_bps": self.config.tc_configs.get(
                                      tc, CBSTCConfig()).idle_slope_bps,
                "enabled":        self.config.tc_configs.get(
                                      tc, CBSTCConfig()).enabled,
                "can_tx":         True,
            } for tc in range(NUM_TC)}

    def get_stats(self) -> Dict:
        return self._stats.snapshot()

class CBSStats:
    def __init__(self, port_id):
        self.port_id = port_id
        self._lock   = threading.Lock()
        self.sent    = {tc: 0 for tc in range(NUM_TC)}
        self.queued  = {tc: 0 for tc in range(NUM_TC)}
        self.dropped = {tc: 0 for tc in range(NUM_TC)}

    def record_sent(self, tc, queued=False):
        with self._lock:
            self.sent[tc] = self.sent.get(tc, 0) + 1
            if queued:
                self.queued[tc] = self.queued.get(tc, 0) + 1

    def record_dropped(self, tc):
        with self._lock:
            self.dropped[tc] = self.dropped.get(tc, 0) + 1

    def snapshot(self):
        with self._lock:
            return {"port_id": self.port_id,
                    "sent":    dict(self.sent),
                    "queued":  dict(self.queued),
                    "dropped": dict(self.dropped)}
