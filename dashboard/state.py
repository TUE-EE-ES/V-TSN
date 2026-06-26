import threading
import time
from collections import deque
from typing import Dict, Optional

class NodeInfo:
    def __init__(self, node_id, role, ip):
        self.node_id   = node_id; self.role = role; self.ip = ip
        self.offset_ms = None; self.last_seen = time.time()
        self.history   = deque(maxlen=300); self.status = "unknown"

    def update(self, offset_ms):
        self.offset_ms = offset_ms; self.last_seen = time.time()
        if offset_ms is not None:
            self.history.append({"t": self.last_seen, "v": round(offset_ms, 4)})
        a = abs(offset_ms) if offset_ms is not None else None
        self.status = ("synced"   if a is not None and a < 5  else
                       "drifting" if a is not None and a < 20 else
                       "lost"     if a is not None else "unknown")

    def to_dict(self):
        age = time.time() - self.last_seen
        return {
            "node_id":   self.node_id, "role": self.role, "ip": self.ip,
            "offset_ms": round(self.offset_ms, 4) if self.offset_ms is not None else None,
            "status":    self.status if age < 10 else "offline",
            "last_seen": round(self.last_seen, 2),
            "history":   list(self.history)[-60:],
        }

class NetworkState:
    def __init__(self):
        self.lock       = threading.Lock()
        self.nodes:     Dict[str, NodeInfo] = {}
        self.gm_id      = None
        self.tas_ports: Dict[str, dict] = {}
        self.cbs_ports: Dict[str, dict] = {}
        self._drift_logger = None

    def set_drift_logger(self, drift_logger):
        self._drift_logger = drift_logger

    def update_node(self, node_id, role, offset_ms, ip):
        with self.lock:
            if node_id not in self.nodes:
                self.nodes[node_id] = NodeInfo(node_id, role, ip)
            self.nodes[node_id].update(offset_ms)
            self.nodes[node_id].role = role
            self.nodes[node_id].ip   = ip
            if role == "master":
                self.gm_id = node_id
        if self._drift_logger and offset_ms is not None:
            self._drift_logger.record(node_id, role, offset_ms)

    def update_tas_stats(self, all_stats: dict, all_gates: dict):
        with self.lock:
            for pid in set(list(all_stats) + list(all_gates)):
                self.tas_ports[pid] = {
                    "stats": all_stats.get(pid, {}),
                    "gates": {str(k): v for k, v in
                              all_gates.get(pid, {}).items()},
                }

    def update_cbs_stats(self, all_stats: dict, all_credit: dict):
        with self.lock:
            for pid in set(list(all_stats) + list(all_credit)):
                self.cbs_ports[pid] = {
                    "stats":  all_stats.get(pid, {}),
                    "credit": {str(k): v for k, v in
                               all_credit.get(pid, {}).items()},
                }

    def get_snapshot(self) -> dict:
        with self.lock:
            return {
                "gm_id":     self.gm_id,
                "nodes":     {nid: n.to_dict() for nid, n in self.nodes.items()},
                "timestamp": time.time(),
                "tas_ports": dict(self.tas_ports),
                "cbs_ports": dict(self.cbs_ports),
            }

network_state = NetworkState()
