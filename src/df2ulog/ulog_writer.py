"""Streaming ULog v1 writer (plan §4.3, ADR-03/ADR-07: packed, no padding)."""

from __future__ import annotations

import struct
from typing import BinaryIO

from .errors import UlogWriteError
from .ulog_codec import (
    SYNC_BYTES,
    ULOG_MAGIC,
    ULOG_VERSION,
    UlogFormat,
    sanitize_name,
)

_MAX_RECORD_PAYLOAD = 65535
_MAX_DATA_RECORD = 60000


class UlogWriter:
    """Write ULog v1 records sequentially to a binary file object.

    Record order is not enforced here (the converter/linter enforce the frozen
    order Header -> B -> I* -> F* -> P* -> A* -> (D|L)* -> S); the writer only
    validates per-record field ranges and sizes.
    """

    def __init__(self, fp: BinaryIO, start_timestamp_us: int) -> None:
        self._fp = fp
        self.counts: dict[str, int] = {}
        fp.write(ULOG_MAGIC + bytes([ULOG_VERSION]) + struct.pack("<Q", start_timestamp_us))

    def _record(self, type_char: str, payload: bytes) -> None:
        if len(payload) > _MAX_RECORD_PAYLOAD:
            raise UlogWriteError(
                f"record {type_char!r} payload too large: {len(payload)} B"
            )
        self._fp.write(struct.pack("<HB", len(payload), ord(type_char)) + payload)
        self.counts[type_char] = self.counts.get(type_char, 0) + 1

    def write_flag_bits(self) -> None:
        self._record("B", b"\x00" * 40)

    def write_info(self, key: str, value: str) -> None:
        raw = value.encode("utf-8")
        key_bytes = f"char[{len(raw)}] {sanitize_name(key)}".encode()
        if len(key_bytes) > 255:
            raise UlogWriteError(f"info key too long: {key!r}")
        self._record("I", bytes([len(key_bytes)]) + key_bytes + raw)

    def write_initial_parameter(self, name: str, value: float) -> None:
        key_bytes = f"float {sanitize_name(name)}".encode()
        if len(key_bytes) > 255:
            raise UlogWriteError(f"parameter name too long: {name!r}")
        try:
            packed = struct.pack("<f", float(value))
        except (struct.error, OverflowError, TypeError, ValueError) as exc:
            raise UlogWriteError(f"cannot pack parameter {name!r}: {exc}") from exc
        self._record("P", bytes([len(key_bytes)]) + key_bytes + packed)

    def write_format(self, fmt: UlogFormat) -> None:
        self._record("F", fmt.format_string().encode("utf-8"))

    def write_add_logged(self, msg_id: int, name: str, multi_id: int = 0) -> None:
        if not 0 <= msg_id <= 0xFFFF:
            raise UlogWriteError(f"msg_id out of range: {msg_id}")
        if not 0 <= multi_id <= 0xFF:
            raise UlogWriteError(f"multi_id out of range: {multi_id}")
        name_bytes = name.encode("utf-8")
        if not name_bytes or len(name_bytes) > 255:
            raise UlogWriteError(f"invalid logged message name: {name!r}")
        self._record("A", struct.pack("<BH", multi_id, msg_id) + name_bytes)

    def write_data(self, msg_id: int, payload: bytes) -> None:
        if not 0 <= msg_id <= 0xFFFF:
            raise UlogWriteError(f"msg_id out of range: {msg_id}")
        if len(payload) < 8:
            raise UlogWriteError(
                f"data payload must start with uint64 timestamp, got {len(payload)} B"
            )
        if 2 + len(payload) > _MAX_DATA_RECORD:
            raise UlogWriteError(f"data payload too large: {len(payload)} B")
        self._record("D", struct.pack("<H", msg_id) + payload)

    def write_logging(self, timestamp_us: int, text: str, level: str = "6") -> None:
        if len(level) != 1 or level not in "01234567":
            raise UlogWriteError(f"invalid log level: {level!r} (must be '0'..'7')")
        self._record(
            "L", struct.pack("<BQ", ord(level), timestamp_us) + text.encode("utf-8")
        )

    def write_sync(self) -> None:
        self._record("S", SYNC_BYTES)

    def flush(self) -> None:
        self._fp.flush()
