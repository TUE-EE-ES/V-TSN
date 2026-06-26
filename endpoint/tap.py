import os
import struct
import fcntl
import subprocess
import logging
import threading

logger = logging.getLogger(__name__)

TUNSETIFF   = 0x400454CA
IFF_TAP     = 0x0002
IFF_NO_PI   = 0x1000

class TAPInterface:

    def __init__(self, name: str = "tsn0", ip: str = "10.100.0.1",
                 netmask: str = "255.255.255.0", mtu: int = 1500):
        self.name    = name
        self.ip      = ip
        self.netmask = netmask
        self.mtu     = mtu
        self._fd     = None
        self._file   = None

    def open(self):
        self._fd = os.open("/dev/net/tun", os.O_RDWR)

        ifr = struct.pack("16sH", self.name.encode(), IFF_TAP | IFF_NO_PI)
        fcntl.ioctl(self._fd, TUNSETIFF, ifr)

        self._run(f"ip link set {self.name} up")
        self._run(f"ip addr add {self.ip}/{self._prefix(self.netmask)} "
                  f"dev {self.name}")
        self._run(f"ip link set {self.name} mtu {self.mtu}")

        self._file = os.fdopen(self._fd, "rb+", buffering=0)
        logger.info("[TAP] Interface %s up, IP=%s", self.name, self.ip)

    def close(self):
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
        self._run(f"ip link set {self.name} down 2>/dev/null || true")
        logger.info("[TAP] Interface %s closed", self.name)

    def read(self, size: int = 4096) -> bytes:
        return self._file.read(size)

    def write(self, data: bytes):
        self._file.write(data)
        self._file.flush()

    def fileno(self) -> int:
        return self._fd

    @staticmethod
    def _run(cmd: str):
        result = subprocess.run(cmd, shell=True, capture_output=True)
        if result.returncode != 0:
            logger.warning("[TAP] cmd failed: %s — %s",
                           cmd, result.stderr.decode().strip())

    @staticmethod
    def _prefix(netmask: str) -> int:
        return sum(bin(int(x)).count("1") for x in netmask.split("."))

    def is_available(self) -> bool:
        return os.path.exists("/dev/net/tun")
