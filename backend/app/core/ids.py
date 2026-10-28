"""Identifiers: UUIDv7 (RFC 9562)."""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last_ms = 0
_last_seq = 0


def _uuid7_local() -> uuid.UUID:
    """UUIDv7: 48-bit unix ms timestamp, version 7, 12-bit rand_a, variant, 62-bit rand_b.

    rand_a acts as a counter within one millisecond, so consecutive ids are monotonic.
    """
    global _last_ms, _last_seq
    with _lock:
        ms = time.time_ns() // 1_000_000
        if ms <= _last_ms:
            ms = _last_ms
            seq = _last_seq + 1
            if seq > 0xFFF:
                ms += 1
                seq = int.from_bytes(os.urandom(2)) & 0x7FF
        else:
            seq = int.from_bytes(os.urandom(2)) & 0x7FF
        _last_ms, _last_seq = ms, seq
    rand_b = int.from_bytes(os.urandom(8)) & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | seq << 64 | 0b10 << 62 | rand_b
    return uuid.UUID(int=value)


def new_id() -> uuid.UUID:
    uuid7 = getattr(uuid, "uuid7", None)
    if uuid7 is not None:
        result: uuid.UUID = uuid7()
        return result
    return _uuid7_local()
