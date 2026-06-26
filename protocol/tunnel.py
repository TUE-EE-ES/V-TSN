import struct

TUNNEL_MAGIC    = 0x5456
TUNNEL_HDR_FMT  = "!H H B 3s"
TUNNEL_HDR_SIZE = struct.calcsize(TUNNEL_HDR_FMT)

ETHERTYPE_GPTP  = 0x88F7
ETHERTYPE_DATA  = 0x0800

class TunnelFrame:
    def __init__(self, ethertype: int, tc: int, payload: bytes):
        self.ethertype = ethertype
        self.tc = tc
        self.payload = payload

    def encode(self) -> bytes:
        hdr = struct.pack(TUNNEL_HDR_FMT,
                          TUNNEL_MAGIC,
                          self.ethertype,
                          self.tc & 0xFF,
                          b'\x00\x00\x00')
        return hdr + self.payload

    @classmethod
    def decode(cls, data: bytes):
        if len(data) < TUNNEL_HDR_SIZE:
            return None
        magic, ethertype, tc, _ = struct.unpack(
            TUNNEL_HDR_FMT, data[:TUNNEL_HDR_SIZE])
        if magic != TUNNEL_MAGIC:
            return None
        return cls(ethertype, tc, data[TUNNEL_HDR_SIZE:])

    def is_gptp(self) -> bool:
        return self.ethertype == ETHERTYPE_GPTP

    def is_data(self) -> bool:
        return self.ethertype == ETHERTYPE_DATA
