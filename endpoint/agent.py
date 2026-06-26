import socket
import threading
import logging
import time
import os
import struct
from typing import Optional, Callable

from protocol.tunnel import TunnelFrame, ETHERTYPE_GPTP, ETHERTYPE_DATA

logger = logging.getLogger(__name__)

TUNNEL_PORT   = 4789
BUFFER_SIZE   = 8192

def _extract_tc_from_frame(frame: bytes) -> int:
    if len(frame) < 14:
        return 0

    ethertype = struct.unpack("!H", frame[12:14])[0]

    if ethertype == ETHERTYPE_GPTP:
        return 3

    if ethertype == 0x8100 and len(frame) >= 16:
        pcp = (struct.unpack("!H", frame[14:16])[0] >> 13) & 0x7
        return min(3, pcp // 2)

    if ethertype == 0x0800 and len(frame) >= 23:
        dscp = (frame[15] >> 2) & 0x3F
        if dscp >= 46:
            return 3
        if dscp >= 18:
            return 2
        if dscp >= 8:
            return 1
        return 0

    return 0

def _get_ethertype(frame: bytes) -> int:
    if len(frame) < 14:
        return 0
    return struct.unpack("!H", frame[12:14])[0]

class EndpointAgent:

    def __init__(self, config: dict):
        self.config      = config
        self.node_id     = config["node_id"]
        self.switch_ip   = config["switch_ip"]
        self.switch_port = config.get("switch_tunnel_port", TUNNEL_PORT)
        self.tunnel_port = config.get("tunnel_port", TUNNEL_PORT)
        self.tap_name    = config.get("tap_name", "tsn0")
        self.tap_ip      = config.get("tap_ip", "10.100.0.1")
        self.tap_netmask = config.get("tap_netmask", "255.255.255.0")

        self.running     = False
        self._tap        = None
        self._sock       = None
        self._tap_mode   = False

        self._data_handler: Optional[Callable] = None
        self._gptp_handler: Optional[Callable] = None

        self.stats = {
            "tx_packets": 0, "rx_packets": 0,
            "tx_bytes": 0,   "rx_bytes": 0,
            "tx_timestamps": [], "rx_timestamps": [],
        }
        self._stats_lock = threading.Lock()

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.tunnel_port))
        self._sock.settimeout(1.0)

        if os.path.exists("/dev/net/tun"):
            try:
                from .tap import TAPInterface
                self._tap = TAPInterface(
                    name=self.tap_name,
                    ip=self.tap_ip,
                    netmask=self.tap_netmask
                )
                self._tap.open()
                self._tap_mode = True
                logger.info("[EndpointAgent] TAP mode: %s (%s)",
                            self.tap_name, self.tap_ip)
            except Exception as e:
                logger.warning("[EndpointAgent] TAP unavailable (%s) — "
                               "fallback mode", e)
                self._tap_mode = False
        else:
            logger.info("[EndpointAgent] No /dev/net/tun — fallback mode")
            self._tap_mode = False

        self.running = True

        threading.Thread(target=self._tunnel_recv_loop,
                         daemon=True, name="ep-tunnel-rx").start()

        if self._tap_mode:
            threading.Thread(target=self._tap_reader_loop,
                             daemon=True, name="ep-tap-tx").start()

        logger.info("[EndpointAgent] %s started. Switch=%s:%d mode=%s",
                    self.node_id, self.switch_ip, self.switch_port,
                    "TAP" if self._tap_mode else "fallback")

    def stop(self):
        self.running = False
        if self._tap:
            self._tap.close()
        if self._sock:
            self._sock.close()
        logger.info("[EndpointAgent] %s stopped", self.node_id)

    def _tap_reader_loop(self):
        while self.running:
            try:
                frame = self._tap.read(BUFFER_SIZE)
                if not frame:
                    continue
                self._send_to_switch(frame)
            except Exception as e:
                if self.running:
                    logger.debug("[EndpointAgent] TAP read error: %s", e)

    def _send_to_switch(self, frame: bytes):
        ethertype = _get_ethertype(frame)
        tc        = _extract_tc_from_frame(frame)
        ts        = int(time.time() * 1e9)

        tunnel_frame = TunnelFrame(ethertype, tc, frame)
        data = tunnel_frame.encode()

        try:
            self._sock.sendto(data, (self.switch_ip, self.switch_port))
            with self._stats_lock:
                self.stats["tx_packets"] += 1
                self.stats["tx_bytes"]   += len(data)
                self.stats["tx_timestamps"].append(ts)
                if len(self.stats["tx_timestamps"]) > 100:
                    self.stats["tx_timestamps"].pop(0)
        except Exception as e:
            logger.warning("[EndpointAgent] Tunnel send error: %s", e)

    def _tunnel_recv_loop(self):
        while self.running:
            try:
                data, addr = self._sock.recvfrom(BUFFER_SIZE)
                ts = int(time.time() * 1e9)
                self._handle_tunnel_frame(data, ts, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.debug("[EndpointAgent] Tunnel recv error: %s", e)

    def _handle_tunnel_frame(self, data: bytes, ingress_ts: int, addr):
        frame = TunnelFrame.decode(data)
        if frame is None:
            if self._gptp_handler:
                self._gptp_handler(data, addr)
            return

        with self._stats_lock:
            self.stats["rx_packets"] += 1
            self.stats["rx_bytes"]   += len(data)
            self.stats["rx_timestamps"].append(ingress_ts)
            if len(self.stats["rx_timestamps"]) > 100:
                self.stats["rx_timestamps"].pop(0)

        if self._tap_mode and self._tap:
            try:
                self._tap.write(frame.payload)
            except Exception as e:
                logger.debug("[EndpointAgent] TAP write error: %s", e)
        else:
            if frame.is_gptp() and self._gptp_handler:
                self._gptp_handler(frame.payload, addr)
            elif frame.is_data() and self._data_handler:
                self._data_handler(frame.payload, addr, ingress_ts, frame.tc)

    def set_gptp_handler(self, fn: Callable):
        self._gptp_handler = fn

    def set_data_handler(self, fn: Callable):
        self._data_handler = fn

    def send_data(self, payload: bytes, tc: int = 0):
        dscp_map = {0: 0, 1: 8, 2: 18, 3: 46}
        dscp = dscp_map.get(tc, 0)

        eth_hdr = b'\x00' * 6 + b'\x00\x00\x00\x00\x00\x01'
        eth_hdr += b'\x08\x00'

        ip_hdr = bytes([
            0x45,
            (dscp << 2),
            0x00, 0x00,
            0x00, 0x00,
            0x00, 0x00,
            0x40,
            0x11,
            0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
            0x00, 0x00, 0x00, 0x00,
        ])

        frame = eth_hdr + ip_hdr + payload
        self._send_to_switch(frame)

    def send_gptp(self, payload: bytes):
        eth_hdr = (b'\x01\x80\xC2\x00\x00\x0E'
                   + b'\x00\x00\x00\x00\x00\x01'
                   + b'\x88\xF7')
        frame = eth_hdr + payload
        self._send_to_switch(frame)

    def get_stats(self) -> dict:
        with self._stats_lock:
            return dict(self.stats)

    @property
    def tap_mode(self) -> bool:
        return self._tap_mode
