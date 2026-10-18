"""DataFlash -> ULog mapping: type table, topic planning, payload packing (plan §4.5)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .df_source import DataFlashRegistry, DfFormatSpec, MetadataScan
from .errors import UlogWriteError
from .ulog_codec import (
    SCALAR_STRUCT,
    UlogField,
    UlogFormat,
    pack_field,
    sanitize_name,
)

# Appendix A, frozen table: DF format char -> (ULog basic type or "char", array_len).
DF_TO_ULOG: dict[str, tuple[str, int]] = {
    "a": ("int16_t", 32),
    "b": ("int8_t", 1),
    "B": ("uint8_t", 1),
    "h": ("int16_t", 1),
    "H": ("uint16_t", 1),
    "i": ("int32_t", 1),
    "I": ("uint32_t", 1),
    "q": ("int64_t", 1),
    "Q": ("uint64_t", 1),
    "f": ("float", 1),
    "d": ("double", 1),
    "g": ("float", 1),
    "n": ("char", 4),
    "N": ("char", 16),
    "Z": ("char", 64),
    "c": ("float", 1),
    "C": ("float", 1),
    "e": ("float", 1),
    "E": ("float", 1),
    "L": ("double", 1),
    "M": ("uint8_t", 1),
}

RESERVED_FIELD_NAMES = frozenset({"timestamp"})

_CHAR_ARRAY_LEN = 32


@dataclass(frozen=True)
class FieldPlan:
    name: str
    ulog_type: str
    array_len: int
    source_column: str
    source_index: int
    df_char: str
    unit: str


@dataclass(frozen=True)
class UlogTopicPlan:
    df_type_id: int
    df_name: str
    instance: int | None
    ulog_name: str
    multi_id: int
    timestamp_column: str
    timestamp_multiplier: int
    fields: tuple[FieldPlan, ...]
    ulog_format: UlogFormat

    @property
    def payload_size(self) -> int:
        return self.ulog_format.payload_size()


@dataclass(frozen=True)
class TopicStats:
    count: int
    first_ts_us: int
    last_ts_us: int


def can_map_format(
    spec: DfFormatSpec, registry: DataFlashRegistry
) -> tuple[bool, str | None]:
    """Check the frozen mapping preconditions; returns (ok, reason)."""
    if len(spec.columns) != len(spec.format_chars):
        return False, "column/format count mismatch"
    for char in spec.format_chars:
        if char not in DF_TO_ULOG:
            return False, f"unsupported format char {char!r}"
    if "TimeUS" not in spec.columns and "TimeMS" not in spec.columns:
        return False, "no timestamp column"
    return True, None


def _unique_ulog_names(
    type_ids: list[int],
    registry: DataFlashRegistry,
    warnings: list[str],
) -> dict[int, str]:
    bases: dict[int, str] = {}
    for tid in type_ids:
        spec = registry.formats.get(tid)
        if spec is None:
            warnings.append(f"unknown DF type id {tid} in stats; skipped")
            continue
        bases[tid] = sanitize_name(spec.name)
    names: dict[int, str] = {}
    seen: set[str] = set()
    for tid in sorted(bases):
        base = bases[tid]
        candidate = base
        if candidate in seen:
            candidate = sanitize_name(f"{base}_{tid}")
        while candidate in seen:
            candidate = sanitize_name(f"{candidate}_")
        if candidate != base:
            warnings.append(
                f"DF type {tid} ({base!r}) renamed to {candidate!r} "
                "(sanitised name collision)"
            )
        seen.add(candidate)
        names[tid] = candidate
    return names


def _build_fields(
    spec: DfFormatSpec,
    registry: DataFlashRegistry,
    timestamp_index: int,
    warnings: list[str],
) -> tuple[FieldPlan, ...]:
    units = registry.units_for(spec.type_id)
    fields: list[FieldPlan] = []
    used: set[str] = set()
    for i, (column, df_char) in enumerate(zip(spec.columns, spec.format_chars)):
        if i == timestamp_index:
            continue
        ulog_type, array_len = DF_TO_ULOG[df_char]
        name = sanitize_name(column)
        if name in RESERVED_FIELD_NAMES:
            warnings.append(
                f"DF type {spec.name!r}: field {column!r} -> {name!r} is reserved, "
                "renamed to 'col_timestamp'"
            )
            name = "col_timestamp"
        if name in used:
            base = name
            counter = 2
            while f"{base}_{counter}" in used:
                counter += 1
            name = f"{base}_{counter}"
            warnings.append(
                f"DF type {spec.name!r}: duplicate field {base!r} renamed to {name!r}"
            )
        used.add(name)
        fields.append(
            FieldPlan(
                name=name,
                ulog_type=ulog_type,
                array_len=array_len,
                source_column=column,
                source_index=i,
                df_char=df_char,
                unit=units[i] if i < len(units) else "",
            )
        )
    return tuple(fields)


def build_topic_plans(
    meta: MetadataScan,
    registry: DataFlashRegistry,
    stats: dict[tuple[int, int | None], TopicStats],
) -> tuple[list[UlogTopicPlan], list[str]]:
    """Build one plan per (DF type, instance) pair, sorted by (ulog_name, multi_id)."""
    warnings: list[str] = []
    type_ids = sorted({key[0] for key in stats})
    ulog_names = _unique_ulog_names(type_ids, registry, warnings)
    plans: list[UlogTopicPlan] = []
    for tid, instance in stats:
        spec = registry.formats.get(tid)
        if spec is None:
            continue
        ok, reason = can_map_format(spec, registry)
        if not ok:
            warnings.append(f"DF type {spec.name!r} not mappable: {reason}")
            continue
        if "TimeUS" in spec.columns:
            timestamp_column, timestamp_multiplier = "TimeUS", 1
        else:
            timestamp_column, timestamp_multiplier = "TimeMS", 1000
        timestamp_index = spec.columns.index(timestamp_column)
        fields = _build_fields(spec, registry, timestamp_index, warnings)
        ulog_name = ulog_names.get(tid, sanitize_name(spec.name))
        multi_id = 0 if instance is None else int(instance)
        ulog_format = UlogFormat(
            ulog_name,
            (UlogField("uint64_t", 1, "timestamp"),)
            + tuple(UlogField(f.ulog_type, f.array_len, f.name) for f in fields),
        )
        plans.append(
            UlogTopicPlan(
                df_type_id=tid,
                df_name=spec.name,
                instance=instance,
                ulog_name=ulog_name,
                multi_id=multi_id,
                timestamp_column=timestamp_column,
                timestamp_multiplier=timestamp_multiplier,
                fields=fields,
                ulog_format=ulog_format,
            )
        )
    plans.sort(key=lambda p: (p.ulog_name, p.multi_id))
    return plans, warnings


def _parse_array32(raw) -> list[int]:
    if isinstance(raw, str):
        text = raw.strip()
        text = text.removeprefix("[")
        text = text.removesuffix("]")
        values = [int(token) for token in text.split()] if text.strip() else []
    else:
        values = [int(v) for v in raw]
    if len(values) < _CHAR_ARRAY_LEN:
        values = values + [0] * (_CHAR_ARRAY_LEN - len(values))
    return values[:_CHAR_ARRAY_LEN]


def normalize_value(raw, field: FieldPlan) -> bytes:
    """Convert one DataFlash value to its packed ULog field bytes (ADR-06)."""
    char = field.df_char
    try:
        if char == "a":
            values = _parse_array32(raw)
            return pack_field(
                UlogField("int16_t", _CHAR_ARRAY_LEN, field.name), values
            )
        if char in "nNZ":
            if raw is None:
                value = b""
            elif isinstance(raw, (bytes, bytearray)):
                value = bytes(raw)
            else:
                value = str(raw)
            return pack_field(UlogField("char", field.array_len, field.name), value)
        if char == "M":
            if isinstance(raw, str):
                converted = int(raw)
            else:
                converted = int(raw) & 0xFF
        elif char in "cCeELfdg":
            converted = float(raw)
        else:
            converted = int(raw)
        return pack_field(
            UlogField(field.ulog_type, field.array_len, field.name), converted
        )
    except (UlogWriteError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(
            f"cannot convert field {field.name!r} (DF char {char!r}) "
            f"value {raw!r}: {exc}"
        ) from exc


def build_payload(plan: UlogTopicPlan, msg, timestamp_us: int) -> bytes:
    """Build the full D payload: uint64 timestamp + packed fields (no padding)."""
    return _packer_for(plan).pack(msg, timestamp_us)


_PACKER_CACHE: dict[tuple[FieldPlan, ...], object] = {}

# __getattr__ already returns properly typed/scaled Python values for these chars,
# so the struct module can consume them directly (no per-field conversion call).
_DIRECT_CHARS = frozenset("bBhHiIqQfdcCeELg")


class _FastPacker:
    """All-numeric topic: one struct.pack + one list comp per D record."""

    __slots__ = ("_columns", "_struct", "payload_size")

    def __init__(self, plan: UlogTopicPlan) -> None:
        self._struct = struct.Struct(
            "<Q" + "".join(SCALAR_STRUCT[f.ulog_type] for f in plan.fields)
        )
        self._columns = tuple(field_plan.source_column for field_plan in plan.fields)
        self.payload_size = plan.payload_size

    def pack(self, msg, timestamp_us: int) -> bytes:
        try:
            getter = msg.__getattr__
            payload = self._struct.pack(
                int(timestamp_us), *[getter(column) for column in self._columns]
            )
        except (struct.error, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(f"cannot pack topic payload: {exc}") from exc
        if len(payload) != self.payload_size:
            raise ValueError(
                f"payload size {len(payload)} != planned {self.payload_size}"
            )
        return payload


class _GenericPacker:
    """Topics with char[n]/int16_t[32]/M fields: per-field conversion, one pack."""

    __slots__ = ("_fields", "_struct", "payload_size")

    def __init__(self, plan: UlogTopicPlan) -> None:
        parts: list[str] = ["<Q"]
        for field_plan in plan.fields:
            if field_plan.ulog_type == "char":
                parts.append(f"{field_plan.array_len}s")
            else:
                parts.append(SCALAR_STRUCT[field_plan.ulog_type] * field_plan.array_len)
        self._struct = struct.Struct("".join(parts))
        self._fields = plan.fields
        self.payload_size = plan.payload_size

    def pack(self, msg, timestamp_us: int) -> bytes:
        values: list = [int(timestamp_us)]
        current = "<init>"
        try:
            getter = msg.__getattr__
            for field_plan in self._fields:
                current = field_plan.name
                raw = getter(field_plan.source_column)
                char = field_plan.df_char
                if char == "a":
                    values.extend(_parse_array32(raw))
                elif char in "nNZ":
                    if raw is None:
                        values.append(b"")
                    elif isinstance(raw, (bytes, bytearray)):
                        values.append(bytes(raw))
                    else:
                        values.append(str(raw).encode("utf-8"))
                elif char == "M":
                    values.append(
                        int(raw) if isinstance(raw, str) else int(raw) & 0xFF
                    )
                elif char in "cCeELfdg":
                    values.append(float(raw))
                else:
                    values.append(int(raw))
            payload = self._struct.pack(*values)
        except (struct.error, TypeError, ValueError, AttributeError) as exc:
            raise ValueError(
                f"cannot convert field {current!r} (topic payload packing): {exc}"
            ) from exc
        if len(payload) != self.payload_size:
            raise ValueError(
                f"payload size {len(payload)} != planned {self.payload_size}"
            )
        return payload


def _packer_for(plan: UlogTopicPlan):
    packer = _PACKER_CACHE.get(plan.fields)
    if packer is None:
        if all(field_plan.df_char in _DIRECT_CHARS for field_plan in plan.fields):
            packer = _FastPacker(plan)
        else:
            packer = _GenericPacker(plan)
        _PACKER_CACHE[plan.fields] = packer
    return packer
