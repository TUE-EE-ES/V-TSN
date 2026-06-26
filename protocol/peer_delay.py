import time
import threading
import logging
from typing import Optional, Callable

from .messages import (
    PdelayReqMsg, PdelayRespMsg, PdelayRespFUMsg, MsgType
)
from core.filter import DelayFilter
from core.clock import LocalClock

logger = logging.getLogger(__name__)

class PeerDelaySession:

    def __init__(self, node_id: str, peer_id: str,
                 peer_ip: str, peer_port: int,
                 clock: LocalClock,
                 send_fn: Callable,
                 interval_s: float = 1.0):
        self.node_id = node_id
        self.peer_id = peer_id
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.clock = clock
        self.send_fn = send_fn
        self.interval_s = interval_s

        self.delay_filter = DelayFilter(window=32)
        self.seq_id = 0
        self.pending = {}
        self.lock = threading.Lock()

        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"pdelay-{self.peer_id}")
        self._thread.start()

    def stop(self):
        self._running = False

    def _run(self):
        while self._running:
            self._send_req()
            time.sleep(self.interval_s)

    def _send_req(self):
        t1 = self.clock.now_ns()
        seq = self.seq_id
        self.seq_id = (self.seq_id + 1) & 0xFFFFFFFF

        with self.lock:
            self.pending[seq] = {"t1": t1, "t2": None, "t3": None}
            old = [s for s in self.pending
                   if self.pending[s]["t1"] < t1 - 10_000_000_000]
            for s in old:
                del self.pending[s]

        msg = PdelayReqMsg(seq, self.node_id, t1)
        self.send_fn(msg.encode(), self.peer_ip, self.peer_port)
        logger.debug(f"[{self.node_id}] PdelayReq seq={seq} to {self.peer_id}")

    def on_resp(self, msg: PdelayRespMsg):
        with self.lock:
            if msg.seq_id in self.pending:
                self.pending[msg.seq_id]["t2"] = msg.t2_ns

    def on_resp_fu(self, msg: PdelayRespFUMsg):
        t4 = self.clock.now_ns()
        with self.lock:
            entry = self.pending.get(msg.seq_id)
            if not entry:
                return
            t1 = entry["t1"]
            t2 = entry.get("t2")
            t3 = msg.t3_ns

            if t1 and t2 and t3:
                delay = ((t4 - t1) - (t3 - t2)) // 2
                if delay > 0:
                    self.delay_filter.add(delay)
                    logger.debug(
                        f"[{self.node_id}] PeerDelay to {self.peer_id}: "
                        f"{delay/1e6:.3f}ms (filtered: {self.get_delay()/1e6:.3f}ms)")
                del self.pending[msg.seq_id]

    def get_delay(self) -> int:
        return self.delay_filter.get_best()

    def is_ready(self) -> bool:
        return self.delay_filter.is_ready()

class PeerDelayResponder:

    def __init__(self, node_id: str, clock: LocalClock, send_fn: Callable):
        self.node_id = node_id
        self.clock = clock
        self.send_fn = send_fn

    def on_req(self, msg: PdelayReqMsg, src_ip: str, src_port: int):
        t2 = self.clock.now_ns()

        resp = PdelayRespMsg(
            seq_id=msg.seq_id,
            node_id=self.node_id,
            t2_ns=t2,
            t1_echo_ns=msg.t1_ns,
            req_node_id=msg.node_id
        )
        self.send_fn(resp.encode(), src_ip, src_port)

        t3 = self.clock.now_ns()
        fu = PdelayRespFUMsg(
            seq_id=msg.seq_id,
            node_id=self.node_id,
            t3_ns=t3,
            t1_echo_ns=msg.t1_ns,
            req_node_id=msg.node_id
        )
        self.send_fn(fu.encode(), src_ip, src_port)
        logger.debug(
            f"[{self.node_id}] PdelayResp+FU to {msg.node_id} seq={msg.seq_id}")
