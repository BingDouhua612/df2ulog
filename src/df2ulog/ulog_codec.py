"""ULog v1 codec: constants, basic types, formats and field packing (plan §4.2)."""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

from .errors import UlogWriteError

ULOG_MAGIC: bytes = b"\x55\x4c\x6f\x67\x01\x12\x35"  # 7 bytes
ULOG_VERSION: int = 1
SYNC_BYTES: bytes = bytes.fromhex("2f731320250cbb12")


@dataclass(frozen=True)
class BasicType:
    name: str
    struct_char: str
    size: int
    alignment: int


BASIC_TYPES: dict[str, BasicType] = {
    "int8_t": BasicType("int8_t", "b", 1, 1),
    "uint8_t": BasicType("uint8_t", "B", 1, 1),
    "int16_t": BasicType("int16_t", "h", 2, 2),
    "uint16_t": BasicType("uint16_t", "H", 2, 2),
    "int32_t": BasicType("int32_t", "i", 4, 4),
    "uint32_t": BasicType("uint32_t", "I", 4, 4),
    "int64_t": BasicType("int64_t", "q", 8, 8),
    "uint64_t": BasicType("uint64_t", "Q", 8, 8),
    "float": BasicType("float", "f", 4, 4),
    "double": BasicType("double", "d", 8, 8),
    "bool": BasicType("bool", "?", 1, 1),
}

SCALAR_STRUCT: dict[str, str] = {name: bt.struct_char for name, bt in BASIC_TYPES.items()}

_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_]")


def sanitize_name(raw: str, *, max_len: int = 63, fallback: str = "field") -> str:
    """Keep only [A-Za-z0-9_]; prefix '_' if the first char is not a letter/'_'; truncate."""
    name = _SANITIZE_RE.sub("_", raw)
    if not name:
        name = fallback
    if name[0].isdigit():
        name = "_" + name
    return name[:max_len]


@dataclass(frozen=True)
class UlogField:
    ulog_type: str
    array_len: int
    name: str

    @property
    def size_bytes(self) -> int:
        if self.ulog_type == "char":
            return self.array_len
        try:
            base = BASIC_TYPES[self.ulog_type]
        except KeyError as exc:
            raise UlogWriteError(f"unknown ULog field type: {self.ulog_type!r}") from exc
        return base.size * self.array_len


@dataclass(frozen=True)
class UlogFormat:
    name: str
    fields: tuple[UlogField, ...]

    def format_string(self) -> str:
        parts: list[str] = []
        for field in self.fields:
            if field.ulog_type == "char":
                parts.append(f"char[{field.array_len}] {field.name};")
            elif field.array_len == 1:
                parts.append(f"{field.ulog_type} {field.name};")
            else:
                parts.append(f"{field.ulog_type}[{field.array_len}] {field.name};")
        return f"{self.name}:" + "".join(parts)

    def payload_size(self) -> int:
        return sum(field.size_bytes for field in self.fields)


def pack_field(field: UlogField, value) -> bytes:
    """Pack one field into little-endian bytes (scalar, array or char[N])."""
    if field.ulog_type == "char":
        if isinstance(value, str):
            raw = value.encode("utf-8")
        elif isinstance(value, (bytes, bytearray)):
            raw = bytes(value)
        else:
            raise UlogWriteError(
                f"char field {field.name!r} requires string/bytes, got {type(value)!r}"
            )
        return raw[: field.array_len].ljust(field.array_len, b"\x00")

    try:
        base = BASIC_TYPES[field.ulog_type]
    except KeyError as exc:
        raise UlogWriteError(f"unknown ULog field type: {field.ulog_type!r}") from exc
    try:
        if field.array_len == 1:
            return struct.pack("<" + base.struct_char, value)
        values = list(value)
        if len(values) != field.array_len:
            raise UlogWriteError(
                f"field {field.name!r} expects {field.array_len} values, "
                f"got {len(values)}"
            )
        return struct.pack("<" + base.struct_char * field.array_len, *values)
    except UlogWriteError:
        raise
    except (struct.error, OverflowError, TypeError) as exc:
        raise UlogWriteError(
            f"cannot pack field {field.name!r} ({field.ulog_type}): {exc}"
        ) from exc
