import threading
import time
import logging

from .base_node import BaseNode
from protocol.messages import SyncMsg, FollowUpMsg, ProbeRespMsg, ProbeReqMsg
from core.reporter import DashboardReporter

logger = logging.getLogger(__name__)

class GrandMaster(BaseNode):

    def __init__(self, config: dict):
        super().__init__(config)
        self.sync_interval_s = config.get("sync_interval_ms", 125) / 1000.0
        self.seq_id = 0
        self._reporter = None

    def _on_start(self):
        dashboard_url = self.config.get("dashboard_url")
        if dashboard_url:
            self._reporter = DashboardReporter(
                node_id=self.node_id,
                role="master",
                ip=self.config.get("public_ip", "?"),
                dashboard_url=dashboard_url
            )
            self._reporter.update_offset(0.0)
            self._reporter.start()

        threading.Thread(target=self._sync_loop,
                         daemon=True, name="gm-sync").start()
        logger.info(f"[{self.node_id}] Grand Master started "
                    f"(sync={self.sync_interval_s*1000:.0f}ms)")

    def _sync_loop(self):
        time.sleep(2.0)
        while self.running:
            self._send_sync()
            time.sleep(self.sync_interval_s)

    def _send_sync(self):
        peers = self.config.get("peers", [])
        if not peers:
            return
        seq = self.seq_id
        self.seq_id = (self.seq_id + 1) & 0xFFFFFFFF

        sync_data = SyncMsg(seq, self.node_id, self.clock.now_ns()).encode()
        precise_ts = self.clock.now_ns()
        fu_data = FollowUpMsg(seq, self.node_id, precise_ts, 0).encode()

        for peer in peers:
            ip = peer["ip"]
            port = peer.get("port", self.port)
            self._send(sync_data, ip, port)
            self._send(fu_data, ip, port)

        logger.debug(f"[{self.node_id}] Sync seq={seq}")

    def _on_probe_req(self, msg: ProbeReqMsg, src_ip: str, src_port: int):
        t2 = self.clock.now_ns()
        resp = ProbeRespMsg(
            seq_id=msg.seq_id,
            node_id=self.node_id,
            t1_echo_ns=msg.t1_ns,
            t2_ns=t2,
            t3_ns=self.clock.now_ns()
        )
        self.sock.sendto(resp.encode(), (src_ip, src_port))
        logger.debug(f"[{self.node_id}] ProbeResp to {msg.node_id}")

    def run_forever(self):
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info(f"[{self.node_id}] Shutting down...")
            self.stop()
