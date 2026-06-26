import socket
import threading
import logging
import time
from typing import Dict, Tuple

from protocol.messages import decode_message, MsgType
from protocol.peer_delay import PeerDelaySession, PeerDelayResponder
from core.clock import LocalClock

logger = logging.getLogger(__name__)

BUFFER_SIZE = 4096

class BaseNode:

    def __init__(self, config: dict):
        self.config = config
        self.node_id = config["node_id"]
        self.bind_ip = config.get("bind_ip", "0.0.0.0")
        self.port = config.get("port", 319)
        self.role = config["role"]

        self.clock = LocalClock()
        self.running = False

        self.sock = None

        self.pdelay_sessions: Dict[str, PeerDelaySession] = {}

        self.pdelay_responder = PeerDelayResponder(
            self.node_id, self.clock, self._send)

        self.peer_addrs: Dict[str, Tuple[str, int]] = {}

        self._recv_thread = None

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.bind_ip, self.port))
        self.sock.settimeout(1.0)
        self.running = True

        logger.info(f"[{self.node_id}] Started as {self.role} on port {self.port}")

        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True, name=f"recv-{self.node_id}")
        self._recv_thread.start()

        self._setup_peers()
        self._on_start()

    def stop(self):
        self.running = False
        for s in self.pdelay_sessions.values():
            s.stop()
        if self.sock:
            self.sock.close()
        logger.info(f"[{self.node_id}] Stopped")

    def _on_start(self):
        pass

    def _on_sync(self, msg, src_ip, src_port):
        pass

    def _on_follow_up(self, msg, src_ip, src_port):
        pass

    def _on_probe_req(self, msg, src_ip, src_port):
        pass

    def _on_probe_resp(self, msg, src_ip, src_port):
        pass

    def _on_announce(self, msg, src_ip, src_port):
        pass

    def _setup_peers(self):
        peers = self.config.get("peers", [])
        for peer in peers:
            pid = peer["node_id"]
            pip = peer["ip"]
            pport = peer.get("port", self.port)
            self.peer_addrs[pid] = (pip, pport)
            self._add_pdelay_session(pid, pip, pport)

    def _add_pdelay_session(self, peer_id: str, peer_ip: str, peer_port: int):
        interval = self.config.get("pdelay_interval_ms", 1000) / 1000.0
        session = PeerDelaySession(
            node_id=self.node_id,
            peer_id=peer_id,
            peer_ip=peer_ip,
            peer_port=peer_port,
            clock=self.clock,
            send_fn=self._send,
            interval_s=interval
        )
        self.pdelay_sessions[peer_id] = session
        session.start()
        logger.info(f"[{self.node_id}] PeerDelay session started with {peer_id}")

    def _send(self, data: bytes, ip: str, port: int):
        try:
            self.sock.sendto(data, (ip, port))
        except Exception as e:
            logger.warning(f"[{self.node_id}] Send error to {ip}:{port}: {e}")

    def _recv_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                src_ip, src_port = addr
                self._dispatch(data, src_ip, src_port)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.warning(f"[{self.node_id}] Recv error: {e}")

    def _dispatch(self, data: bytes, src_ip: str, src_port: int):
        msg_type, msg = decode_message(data)
        if msg is None:
            return

        if msg_type == MsgType.PDELAY_REQ:
            self.pdelay_responder.on_req(msg, src_ip, src_port)

        elif msg_type == MsgType.PDELAY_RESP:
            session = self.pdelay_sessions.get(msg.node_id)
            if session:
                session.on_resp(msg)

        elif msg_type == MsgType.PDELAY_RESP_FU:
            session = self.pdelay_sessions.get(msg.node_id)
            if session:
                session.on_resp_fu(msg)

        elif msg_type == MsgType.SYNC:
            self._on_sync(msg, src_ip, src_port)

        elif msg_type == MsgType.FOLLOW_UP:
            self._on_follow_up(msg, src_ip, src_port)

        elif msg_type == MsgType.PROBE_REQ:
            self._on_probe_req(msg, src_ip, src_port)

        elif msg_type == MsgType.PROBE_RESP:
            self._on_probe_resp(msg, src_ip, src_port)

        elif msg_type == MsgType.ANNOUNCE:
            self._on_announce(msg, src_ip, src_port)

    def get_peer_delay(self, peer_id: str) -> int:
        session = self.pdelay_sessions.get(peer_id)
        if session:
            return session.get_delay()
        return 0

    def wait_for_peer_delay(self, peer_id: str, timeout_s: float = 10.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            session = self.pdelay_sessions.get(peer_id)
            if session and session.is_ready():
                return True
            time.sleep(0.1)
        return False
