import threading
import time
import logging
from typing import Dict, Optional
from .base_node import BaseNode
from protocol.messages import SyncMsg, FollowUpMsg, ProbeReqMsg, ProbeRespMsg
from protocol.tunnel import TunnelFrame, ETHERTYPE_GPTP
from accuracy.metrics import AccuracyTracker
from core.reporter import DashboardReporter
from endpoint.agent import EndpointAgent
logger = logging.getLogger(__name__)

class Slave(BaseNode):

    def __init__(self, config: dict):
        super().__init__(config)
        self._pending_sync: Dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self._probe_pending: Dict[int, int] = {}
        self._probe_seq = 0
        self._probe_lock = threading.Lock()
        self.gm_config = config.get('gm_peer')
        self.upstream_id = (config.get('peers') or [{}])[0].get('node_id')
        self.accuracy = AccuracyTracker()
        self._sync_count = 0
        self._synced = False
        self._reporter: Optional[DashboardReporter] = None
        self._endpoint: Optional[EndpointAgent] = None
        if config.get('endpoint'):
            ep_cfg = config['endpoint']
            ep_cfg['node_id'] = config['node_id']
            ep_cfg['switch_ip'] = ep_cfg.get('switch_ip', (config.get('peers') or [{}])[0].get('ip', ''))
            self._endpoint = EndpointAgent(ep_cfg)

    def _on_start(self):
        if self._endpoint:
            self._endpoint.start()
            self._endpoint.set_gptp_handler(self._on_tunnel_gptp)
        dashboard_url = self.config.get('dashboard_url')
        if dashboard_url:
            self._reporter = DashboardReporter(node_id=self.node_id, role='slave', ip=self.config.get('public_ip', '?'), dashboard_url=dashboard_url)
            self._reporter.start()
        probe_interval = self.config.get('probe_interval_ms', 2000) / 1000.0
        threading.Thread(target=self._probe_loop, args=(probe_interval,), daemon=True, name=f'probe-{self.node_id}').start()
        threading.Thread(target=self._metrics_loop, daemon=True, name=f'metrics-{self.node_id}').start()
        logger.info('[%s] Slave started. Upstream: %s, GM: %s, Endpoint: %s', self.node_id, self.upstream_id, self.gm_config['node_id'] if self.gm_config else 'none', 'TAP' if self._endpoint and self._endpoint.tap_mode else 'fallback' if self._endpoint else 'none')

    def _on_tunnel_gptp(self, data: bytes, addr: tuple):
        src_ip, src_port = addr
        self._dispatch(data, src_ip, src_port)

    def _on_sync(self, msg: SyncMsg, src_ip: str, src_port: int):
        ingress_ts = self.clock.now_ns()
        with self._pending_lock:
            self._pending_sync[msg.seq_id] = {'ingress_ts': ingress_ts, 'received_at': time.time()}
            now = time.time()
            old = [s for s, v in self._pending_sync.items() if now - v['received_at'] > 5.0]
            for s in old:
                del self._pending_sync[s]

    def _on_follow_up(self, msg: FollowUpMsg, src_ip: str, src_port: int):
        with self._pending_lock:
            pending = self._pending_sync.pop(msg.seq_id, None)
        if not pending:
            return
        upstream_delay = self.get_peer_delay(self.upstream_id) if self.upstream_id else 0
        true_gm_time = msg.precise_origin_ts_ns + msg.correction_ns + upstream_delay
        offset_ns = pending['ingress_ts'] - true_gm_time
        self.clock.adjust(offset_ns)
        if self._reporter:
            self._reporter.update_offset(offset_ns / 1000000.0)
        self._sync_count += 1
        if not self._synced and self._sync_count >= 5:
            self._synced = True
            logger.info('[%s] Clock converged after %d syncs', self.node_id, self._sync_count)
        logger.debug('[%s] offset=%.3fms upstream_delay=%.3fms', self.node_id, offset_ns / 1000000.0, upstream_delay / 1000000.0)

    def _probe_loop(self, interval_s: float):
        time.sleep(3.0)
        while self.running:
            if self.gm_config:
                t1 = self.clock.now_ns()
                seq = self._probe_seq
                self._probe_seq = self._probe_seq + 1 & 4294967295
                with self._probe_lock:
                    self._probe_pending[seq] = t1
                    old = [s for s, v in self._probe_pending.items() if t1 - v > 10000000000]
                    for s in old:
                        del self._probe_pending[s]
                self._send(ProbeReqMsg(seq, self.node_id, t1).encode(), self.gm_config['ip'], self.gm_config.get('port', self.port))
            time.sleep(interval_s)

    def _on_probe_resp(self, msg: ProbeRespMsg, src_ip: str, src_port: int):
        t4 = self.clock.now_ns()
        with self._probe_lock:
            t1 = self._probe_pending.pop(msg.seq_id, None)
        if t1 is None:
            return
        path_delay = (t4 - t1 - (msg.t3_ns - msg.t2_ns)) // 2
        error_ns = self.clock.now_ns() - (msg.t3_ns + path_delay)
        self.accuracy.add_sample(error_ns, path_delay)
        logger.debug('[%s] Probe error=%.3fms', self.node_id, error_ns / 1000000.0)

    def _metrics_loop(self):
        while self.running:
            time.sleep(10)
            r = self.accuracy.report()
            if r:
                logger.info('[%s] Accuracy: mean=%.3fms p95=%.3fms samples=%d', self.node_id, r['mean_ms'], r['p95_ms'], r['count'])

    def get_endpoint(self) -> Optional[EndpointAgent]:
        return self._endpoint

    def run_forever(self):
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info('[%s] Shutting down...', self.node_id)
            self.stop()
