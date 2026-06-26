import socket
import threading
import time
import logging
from typing import Dict
from .base_node import BaseNode
from protocol.messages import SyncMsg, FollowUpMsg
from protocol.tunnel import TunnelFrame, ETHERTYPE_GPTP, ETHERTYPE_DATA
from dashboard.state import network_state
from tas.engine import TASEngine, TASConfig
from tas.cbs import CBSEngine, CBSConfig
from tas.store import TASConfigStore
logger = logging.getLogger(__name__)
TUNNEL_PORT = 4789
BUFFER_SIZE = 8192

class VirtualSwitch(BaseNode):

    def __init__(self, config: dict):
        super().__init__(config)
        self._pending_sync: Dict[int, dict] = {}
        self._pending_lock = threading.Lock()
        self.upstream_peer = config.get('upstream_peer')
        self.downstream_peers = config.get('downstream_peers', [])
        self._tunnel_port = config.get('tunnel_port', TUNNEL_PORT)
        self._tunnel_sock = None
        port_ids = [p['node_id'] for p in self.downstream_peers]
        self._tas_store = TASConfigStore(port_ids=port_ids, path=config.get('tas_config_path', 'tas_config.json'))
        self._tas_engines: Dict[str, TASEngine] = {}
        self._cbs_engines: Dict[str, CBSEngine] = {}
        for peer in self.downstream_peers:
            pid = peer['node_id']
            self._tas_engines[pid] = TASEngine(port_id=pid, config=self._tas_store.get_tas(pid), clock_fn=self.clock.now_ns)
            self._cbs_engines[pid] = CBSEngine(port_id=pid, config=self._tas_store.get_cbs(pid), clock_fn=self.clock.now_ns)
        self._tas_store.add_listener(self._on_config_update)

    def _on_config_update(self, port_id: str, new_tas: TASConfig, new_cbs: CBSConfig):
        if port_id in self._tas_engines:
            self._tas_engines[port_id].update_config(new_tas)
        if port_id in self._cbs_engines:
            self._cbs_engines[port_id].update_config(new_cbs)
        logger.info('[Switch] Config updated for port %s', port_id)

    def _on_start(self):
        if self.upstream_peer:
            pid = self.upstream_peer['node_id']
            pip = self.upstream_peer['ip']
            pport = self.upstream_peer.get('port', self.port)
            self.peer_addrs[pid] = (pip, pport)
            self._add_pdelay_session(pid, pip, pport)
        for peer in self.downstream_peers:
            pid = peer['node_id']
            pip = peer['ip']
            pport = peer.get('port', self.port)
            self.peer_addrs[pid] = (pip, pport)
            self._add_pdelay_session(pid, pip, pport)
        network_state.update_node(node_id=self.node_id, role='switch', offset_ms=0.0, ip=self.config.get('bind_ip', '?'))
        for pid in self._tas_engines:
            self._tas_engines[pid].start()
            self._cbs_engines[pid].start()
            logger.info('[Switch] Port %s: TAS + CBS engines started', pid)
        self._start_tunnel_listener()
        self._start_dashboard()
        logger.info('[%s] Virtual Switch ready. Egress ports: %s', self.node_id, list(self._tas_engines.keys()))

    def _start_tunnel_listener(self):
        self._tunnel_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._tunnel_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._tunnel_sock.bind(('0.0.0.0', self._tunnel_port))
        self._tunnel_sock.settimeout(1.0)
        threading.Thread(target=self._tunnel_recv_loop, daemon=True, name='sw-tunnel-rx').start()
        logger.info('[%s] Tunnel listener on port %d', self.node_id, self._tunnel_port)

    def _tunnel_recv_loop(self):
        while self.running:
            try:
                data, addr = self._tunnel_sock.recvfrom(BUFFER_SIZE)
                ingress_ts = self.clock.now_ns()
                self._handle_tunnel_frame(data, addr[0], ingress_ts)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.debug('[Switch] Tunnel recv error: %s', e)

    def _handle_tunnel_frame(self, data: bytes, src_ip: str, ingress_ts: int):
        frame = TunnelFrame.decode(data)
        if frame is None:
            return
        egress_ts = self.clock.now_ns()
        residence_time = egress_ts - ingress_ts
        if frame.is_gptp():
            self._broadcast_raw(data)
        elif frame.is_data():
            self._broadcast_data(data, frame.tc, residence_time)
        all_tas_stats = {pid: e.get_stats() for pid, e in self._tas_engines.items()}
        all_tas_gates = {pid: e.get_gate_state() for pid, e in self._tas_engines.items()}
        all_cbs_stats = {pid: e.get_stats() for pid, e in self._cbs_engines.items()}
        all_cbs_credit = {pid: e.get_credit_info() for pid, e in self._cbs_engines.items()}
        network_state.update_tas_stats(all_tas_stats, all_tas_gates)
        network_state.update_cbs_stats(all_cbs_stats, all_cbs_credit)

    def _broadcast_raw(self, data: bytes):
        for peer in self.downstream_peers:
            self._tunnel_send(data, peer['ip'], peer.get('tunnel_port', self._tunnel_port))

    def _broadcast_data(self, data: bytes, tc: int, residence_time_ns: int):
        for peer in self.downstream_peers:
            pid = peer['node_id']
            pip = peer['ip']
            pport = peer.get('tunnel_port', self._tunnel_port)
            tas = self._tas_engines.get(pid)
            cbs = self._cbs_engines.get(pid)
            if tas and cbs:
                tas.enqueue(tc=tc, data=data, dest_ip=pip, dest_port=pport, send_fn=lambda d, ip, port, _tc=tc, _cbs=cbs: _cbs.check_and_send(_tc, d, ip, port, self._tunnel_send))
            elif tas:
                tas.enqueue(tc=tc, data=data, dest_ip=pip, dest_port=pport, send_fn=self._tunnel_send)
            else:
                self._tunnel_send(data, pip, pport)
            logger.debug('[Switch] Port %s TC%d residence=%.3fms', pid, tc, residence_time_ns / 1000000.0)

    def _tunnel_send(self, data: bytes, ip: str, port: int):
        try:
            self._tunnel_sock.sendto(data, (ip, port))
        except Exception as e:
            logger.warning('[Switch] Tunnel send error: %s', e)

    def _on_sync(self, msg: SyncMsg, src_ip: str, src_port: int):
        ingress_ts = self.clock.now_ns()
        with self._pending_lock:
            self._pending_sync[msg.seq_id] = {'sync_msg': msg, 'ingress_ts': ingress_ts, 'received_at': time.time()}
            now = time.time()
            for s in [k for k, v in self._pending_sync.items() if now - v['received_at'] > 5.0]:
                del self._pending_sync[s]

    def _on_follow_up(self, msg: FollowUpMsg, src_ip: str, src_port: int):
        with self._pending_lock:
            pending = self._pending_sync.pop(msg.seq_id, None)
        if pending is None:
            return
        upstream_delay = self.get_peer_delay(self.upstream_peer['node_id']) if self.upstream_peer else 0
        residence_time = self.clock.now_ns() - pending['ingress_ts']
        total_correction = msg.correction_ns + upstream_delay + residence_time
        network_state.update_node(node_id=self.node_id, role='switch', offset_ms=residence_time / 1000000.0, ip=self.config.get('bind_ip', '?'))
        for peer in self.downstream_peers:
            pip = peer['ip']
            pport = peer.get('port', self.port)
            self._send(SyncMsg(msg.seq_id, self.node_id, pending['sync_msg'].origin_ts_ns).encode(), pip, pport)
            self._send(FollowUpMsg(msg.seq_id, self.node_id, msg.precise_origin_ts_ns, total_correction).encode(), pip, pport)

    def _start_dashboard(self):
        try:
            from dashboard.app import create_app
            app = create_app(self._tas_store)
            dash_port = self.config.get('dashboard_port', 5000)
            threading.Thread(target=lambda: app.run(host='0.0.0.0', port=dash_port, debug=False, use_reloader=False), daemon=True, name='dashboard').start()
            logger.info('[%s] Dashboard on port %d', self.node_id, dash_port)
        except Exception as e:
            logger.warning('[%s] Dashboard failed: %s', self.node_id, e)

    def stop(self):
        for e in self._tas_engines.values():
            e.stop()
        for e in self._cbs_engines.values():
            e.stop()
        super().stop()
        if self._tunnel_sock:
            self._tunnel_sock.close()

    def run_forever(self):
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info('[%s] Shutting down...', self.node_id)
            self.stop()
