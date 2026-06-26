import struct
import enum

class MsgType(enum.IntEnum):
    SYNC              = 0x01
    FOLLOW_UP         = 0x02
    PDELAY_REQ        = 0x03
    PDELAY_RESP       = 0x04
    PDELAY_RESP_FU    = 0x05
    PROBE_REQ         = 0x10
    PROBE_RESP        = 0x11
    ANNOUNCE          = 0x20
    DATA              = 0x30

HEADER_FMT = "!B I 32s"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

def encode_node_id(node_id: str) -> bytes:
    return node_id.encode()[:32].ljust(32, b'\x00')

def decode_node_id(raw: bytes) -> str:
    return raw.rstrip(b'\x00').decode(errors='replace')

class SyncMsg:
    FMT = HEADER_FMT + " q"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str, origin_ts_ns: int):
        self.seq_id = seq_id
        self.node_id = node_id
        self.origin_ts_ns = origin_ts_ns

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.SYNC, self.seq_id,
            encode_node_id(self.node_id),
            self.origin_ts_ns)

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, ots = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), ots)

class FollowUpMsg:
    FMT = HEADER_FMT + " q q"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str,
                 precise_origin_ts_ns: int, correction_ns: int):
        self.seq_id = seq_id
        self.node_id = node_id
        self.precise_origin_ts_ns = precise_origin_ts_ns
        self.correction_ns = correction_ns

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.FOLLOW_UP, self.seq_id,
            encode_node_id(self.node_id),
            self.precise_origin_ts_ns,
            self.correction_ns)

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, pts, corr = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), pts, corr)

class PdelayReqMsg:
    FMT = HEADER_FMT + " q"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str, t1_ns: int):
        self.seq_id = seq_id
        self.node_id = node_id
        self.t1_ns = t1_ns

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.PDELAY_REQ, self.seq_id,
            encode_node_id(self.node_id),
            self.t1_ns)

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, t1 = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), t1)

class PdelayRespMsg:
    FMT = HEADER_FMT + " q q 32s"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str,
                 t2_ns: int, t1_echo_ns: int, req_node_id: str):
        self.seq_id = seq_id
        self.node_id = node_id
        self.t2_ns = t2_ns
        self.t1_echo_ns = t1_echo_ns
        self.req_node_id = req_node_id

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.PDELAY_RESP, self.seq_id,
            encode_node_id(self.node_id),
            self.t2_ns, self.t1_echo_ns,
            encode_node_id(self.req_node_id))

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, t2, t1e, rnid = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), t2, t1e, decode_node_id(rnid))

class PdelayRespFUMsg:
    FMT = HEADER_FMT + " q q 32s"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str,
                 t3_ns: int, t1_echo_ns: int, req_node_id: str):
        self.seq_id = seq_id
        self.node_id = node_id
        self.t3_ns = t3_ns
        self.t1_echo_ns = t1_echo_ns
        self.req_node_id = req_node_id

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.PDELAY_RESP_FU, self.seq_id,
            encode_node_id(self.node_id),
            self.t3_ns, self.t1_echo_ns,
            encode_node_id(self.req_node_id))

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, t3, t1e, rnid = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), t3, t1e, decode_node_id(rnid))

class ProbeReqMsg:
    FMT = HEADER_FMT + " q"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str, t1_ns: int):
        self.seq_id = seq_id
        self.node_id = node_id
        self.t1_ns = t1_ns

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.PROBE_REQ, self.seq_id,
            encode_node_id(self.node_id),
            self.t1_ns)

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, t1 = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), t1)

class ProbeRespMsg:
    FMT = HEADER_FMT + " q q q"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str,
                 t1_echo_ns: int, t2_ns: int, t3_ns: int):
        self.seq_id = seq_id
        self.node_id = node_id
        self.t1_echo_ns = t1_echo_ns
        self.t2_ns = t2_ns
        self.t3_ns = t3_ns

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.PROBE_RESP, self.seq_id,
            encode_node_id(self.node_id),
            self.t1_echo_ns, self.t2_ns, self.t3_ns)

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, t1e, t2, t3 = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), t1e, t2, t3)

class AnnounceMsg:
    FMT = HEADER_FMT + " I B"
    SIZE = struct.calcsize(FMT)

    def __init__(self, seq_id: int, node_id: str,
                 priority: int, clock_class: int):
        self.seq_id = seq_id
        self.node_id = node_id
        self.priority = priority
        self.clock_class = clock_class

    def encode(self) -> bytes:
        return struct.pack(self.FMT,
            MsgType.ANNOUNCE, self.seq_id,
            encode_node_id(self.node_id),
            self.priority, self.clock_class)

    @classmethod
    def decode(cls, data: bytes):
        t, seq, nid, pri, cc = struct.unpack(cls.FMT, data[:cls.SIZE])
        return cls(seq, decode_node_id(nid), pri, cc)

def decode_message(data: bytes):
    if len(data) < 1:
        return None
    msg_type = data[0]
    try:
        if msg_type == MsgType.SYNC:
            return MsgType.SYNC, SyncMsg.decode(data)
        elif msg_type == MsgType.FOLLOW_UP:
            return MsgType.FOLLOW_UP, FollowUpMsg.decode(data)
        elif msg_type == MsgType.PDELAY_REQ:
            return MsgType.PDELAY_REQ, PdelayReqMsg.decode(data)
        elif msg_type == MsgType.PDELAY_RESP:
            return MsgType.PDELAY_RESP, PdelayRespMsg.decode(data)
        elif msg_type == MsgType.PDELAY_RESP_FU:
            return MsgType.PDELAY_RESP_FU, PdelayRespFUMsg.decode(data)
        elif msg_type == MsgType.PROBE_REQ:
            return MsgType.PROBE_REQ, ProbeReqMsg.decode(data)
        elif msg_type == MsgType.PROBE_RESP:
            return MsgType.PROBE_RESP, ProbeRespMsg.decode(data)
        elif msg_type == MsgType.ANNOUNCE:
            return MsgType.ANNOUNCE, AnnounceMsg.decode(data)
        elif msg_type == 0x30:
            return MsgType.DATA, DataMsg.decode(data)
    except Exception:
        pass
    return None, None

class DataMsg:
    TYPE_BYTE = 0x30
    FMT = "!B I 32s B H"
    HEADER_SIZE = struct.calcsize(FMT)
    MAX_PAYLOAD = 1400

    def __init__(self, seq_id: int, node_id: str, tc: int, payload: bytes):
        self.seq_id = seq_id
        self.node_id = node_id
        self.tc = tc
        self.payload = payload

    def encode(self) -> bytes:
        hdr = struct.pack(self.FMT,
            self.TYPE_BYTE, self.seq_id,
            encode_node_id(self.node_id),
            self.tc & 0xFF,
            len(self.payload))
        return hdr + self.payload

    @classmethod
    def decode(cls, data: bytes):
        if len(data) < cls.HEADER_SIZE:
            return None
        t, seq, nid, tc, plen = struct.unpack(cls.FMT, data[:cls.HEADER_SIZE])
        payload = data[cls.HEADER_SIZE: cls.HEADER_SIZE + plen]
        return cls(seq, decode_node_id(nid), tc, payload)
