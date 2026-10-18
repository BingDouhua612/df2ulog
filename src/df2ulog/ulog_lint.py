"""Standalone raw-byte ULog structural linter (plan §4.6 / ADR-15 check 1).

Deliberately stricter than pyulog: D payload length must equal the subscribed
payload size *exactly* (our writer never emits padding), and the file must have
at least one A and one D record.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .ulog_codec import BASIC_TYPES, SYNC_BYTES, ULOG_MAGIC, ULOG_VERSION

_FIELD_RE = re.compile(r"^([A-Za-z0-9_]+)(?:\[(\d+)\])?$")
_RECORD_TYPE_CHARS = ("B", "I", "F", "P", "A", "D", "L", "S")


@dataclass(frozen=True)
class LintIssue:
    severity: Literal["error", "warning"]
    message: str
    offset: int


@dataclass
class LintReport:
    ok: bool
    issues: list[LintIssue] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)

    def errors(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def warnings(self) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == "warning"]


class _Ctx:
    def __init__(self) -> None:
        self.issues: list[LintIssue] = []
        self.stats: dict[str, int] = {c: 0 for c in _RECORD_TYPE_CHARS}
        self.stats["topics"] = 0
        self.stats["data_records"] = 0
        self.stats["first_ts_us"] = 0
        self.stats["last_ts_us"] = 0

    def error(self, message: str, offset: int) -> None:
        self.issues.append(LintIssue("error", message, offset))

    def warning(self, message: str, offset: int) -> None:
        self.issues.append(LintIssue("warning", message, offset))

    def result(self) -> LintReport:
        ok = not any(i.severity == "error" for i in self.issues)
        return LintReport(ok=ok, issues=list(self.issues), stats=dict(self.stats))


def lint_ulog(path: Path) -> LintReport:
    ctx = _Ctx()
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        ctx.error(f"cannot read file: {exc}", 0)
        return ctx.result()

    if len(data) < 16:
        ctx.error(f"file too short for ULog header ({len(data)} B < 16 B)", 0)
        return ctx.result()
    if data[:7] != ULOG_MAGIC:
        ctx.error("bad magic bytes in file header", 0)
    if data[7] != ULOG_VERSION:
        ctx.error(f"unsupported ULog header version {data[7]} (expected 1)", 7)

    formats: dict[str, int] = {}          # format name -> payload size
    subscriptions: dict[int, int] = {}    # msg_id -> payload size
    sub_names: set[tuple[str, int]] = set()
    last_ts: dict[int, int] = {}
    definition_open = True
    seen_sync = False
    any_data = False
    first_ts: int | None = None
    last_ts_global: int | None = None

    off = 16
    record_index = 0
    while off < len(data):
        if off + 3 > len(data):
            ctx.error(f"truncated record header at offset {off}", off)
            break
        msg_size, msg_type = struct.unpack_from("<HB", data, off)
        if msg_size == 0:
            ctx.error(f"zero-length record at offset {off}", off)
            off += 3
            record_index += 1
            continue
        if msg_size > 10000:
            ctx.error(f"record too large ({msg_size} B) at offset {off}", off)
            break
        payload_start = off + 3
        payload_end = payload_start + msg_size
        if payload_end > len(data):
            ctx.error(f"truncated record at offset {off} ({msg_size} B declared)", off)
            break
        payload = data[payload_start:payload_end]
        ch = chr(msg_type)
        if ch in ctx.stats:
            ctx.stats[ch] += 1
        else:
            ctx.stats[ch] = ctx.stats.get(ch, 0) + 1

        if record_index == 0 and ch != "B":
            ctx.error("first record must be flag bits (B)", off)
        if ch == "B":
            if record_index != 0:
                ctx.error("flag bits (B) record must be the first record", off)
            if msg_size != 40:
                ctx.error(
                    f"flag bits record payload must be exactly 40 B, got {msg_size}", off
                )
            elif payload[8:16] != b"\x00" * 8:
                ctx.error("incompat flags must be all zero", off)
        elif ch == "I":
            if not definition_open:
                ctx.error("info (I) record after definitions started (order)", off)
            if not payload:
                ctx.error("info record has empty payload", off)
            else:
                key_len = payload[0]
                key = payload[1 : 1 + key_len]
                if len(key) < key_len or not key:
                    ctx.error("info record key is truncated/empty", off)
                elif not key.startswith(b"char["):
                    ctx.error("info key must be a char[...] string key", off)
        elif ch == "P":
            if not definition_open:
                ctx.error("parameter (P) record after definitions started (order)", off)
            if not payload:
                ctx.error("parameter record has empty payload", off)
            else:
                key_len = payload[0]
                key = payload[1 : 1 + key_len]
                if len(key) < key_len or not key:
                    ctx.error("parameter record key is truncated/empty", off)
                elif not key.startswith(b"float "):
                    ctx.error("parameter key must be a 'float <name>' key", off)
        elif ch == "F":
            if not definition_open:
                ctx.error("format (F) record must appear before the first A (order)", off)
            else:
                _lint_format(ctx, payload, off, formats)
        elif ch == "A":
            definition_open = False
            _lint_add_logged(ctx, payload, off, formats, subscriptions, sub_names)
            ctx.stats["topics"] = len(subscriptions)
        elif ch == "D":
            any_data = True
            ctx.stats["data_records"] += 1
            if len(payload) < 2:
                ctx.error(f"data (D) payload too short ({len(payload)} B)", off)
            else:
                msg_id = struct.unpack_from("<H", payload, 0)[0]
                if msg_id not in subscriptions:
                    ctx.error(
                        f"D record references unknown subscription msg_id={msg_id}",
                        off,
                    )
                else:
                    data_len = len(payload) - 2
                    expected = subscriptions[msg_id]
                    if data_len != expected:
                        ctx.error(
                            f"D payload length {data_len} != subscribed {expected} "
                            f"(length mismatch)",
                            off,
                        )
                    if data_len >= 8:
                        ts = struct.unpack_from("<Q", payload, 2)[0]
                        prev = last_ts.get(msg_id)
                        if prev is not None and ts < prev:
                            ctx.error(
                                f"timestamp not monotonic for msg_id={msg_id}: "
                                f"{ts} < {prev}",
                                off,
                            )
                        last_ts[msg_id] = ts
                        if first_ts is None or ts < first_ts:
                            first_ts = ts
                        if last_ts_global is None or ts > last_ts_global:
                            last_ts_global = ts
        elif ch == "L":
            if len(payload) < 9:
                ctx.error(f"logging (L) payload too short ({len(payload)} B)", off)
        elif ch == "S":
            if payload != SYNC_BYTES:
                ctx.error("sync (S) record payload must be the 8-byte sync magic", off)
            else:
                seen_sync = True
        else:
            ctx.error(
                f"record type {ch!r} not allowed in data segment (order)", off
            )

        off = payload_end
        record_index += 1

    if not subscriptions:
        ctx.error("no subscriptions (A records) found", len(data))
    if not any_data:
        ctx.error("no data (D) records found", len(data))
    if not seen_sync:
        ctx.warning("file does not end with a sync (S) record", len(data))
    ctx.stats["first_ts_us"] = first_ts or 0
    ctx.stats["last_ts_us"] = last_ts_global or 0
    return ctx.result()


def _lint_format(ctx: _Ctx, payload: bytes, off: int, formats: dict[str, int]) -> None:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        ctx.error("format (F) record is not valid UTF-8", off)
        return
    if ":" not in text:
        ctx.error("format (F) record must contain ':'", off)
        return
    name, field_text = text.split(":", 1)
    if not name:
        ctx.error("format name must not be empty", off)
        return
    if name in formats:
        ctx.error(f"format {name!r} defined more than once", off)
        return
    fields = [seg for seg in field_text.split(";") if seg]
    if not fields:
        ctx.error(f"format {name!r} has no fields", off)
        return
    total = 0
    seen_names: set[str] = set()
    parsed: list[tuple[str, int, str]] = []
    for seg in fields:
        parts = seg.split(" ")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            ctx.error(f"format {name!r}: malformed field {seg!r}", off)
            return
        type_str, field_name = parts
        m = _FIELD_RE.match(type_str)
        if not m:
            ctx.error(f"format {name!r}: bad field type {type_str!r}", off)
            return
        base, array_str = m.group(1), m.group(2)
        array_len = int(array_str) if array_str else 1
        if array_len < 1:
            ctx.error(f"format {name!r}: bad array length for {field_name!r}", off)
            return
        if base == "char":
            size = array_len
        elif base in BASIC_TYPES:
            size = BASIC_TYPES[base].size * array_len
        else:
            ctx.error(f"format {name!r}: unknown field type {base!r}", off)
            return
        if not field_name:
            ctx.error(f"format {name!r}: empty field name", off)
            return
        if field_name in seen_names:
            ctx.error(f"format {name!r}: duplicate field name {field_name!r}", off)
            return
        seen_names.add(field_name)
        parsed.append((base, array_len, field_name))
        total += size
    first = parsed[0]
    if first[0] != "uint64_t" or first[2] != "timestamp":
        ctx.error(
            f"format {name!r}: first field must be 'uint64_t timestamp'", off
        )
        return
    formats[name] = total


def _lint_add_logged(
    ctx: _Ctx,
    payload: bytes,
    off: int,
    formats: dict[str, int],
    subscriptions: dict[int, int],
    sub_names: set[tuple[str, int]],
) -> None:
    if len(payload) < 3:
        ctx.error(f"add-logged (A) payload too short ({len(payload)} B)", off)
        return
    multi_id = payload[0]
    msg_id = struct.unpack_from("<H", payload, 1)[0]
    name = payload[3:]
    if not name:
        ctx.error("add-logged (A) name must not be empty", off)
        return
    if len(name) > 255:
        ctx.error("add-logged (A) name longer than 255 B", off)
        return
    try:
        name_str = name.decode("utf-8")
    except UnicodeDecodeError:
        ctx.error("add-logged (A) name is not valid UTF-8", off)
        return
    if msg_id in subscriptions:
        ctx.error(f"duplicate msg_id {msg_id} in add-logged (A) records", off)
    if (name_str, multi_id) in sub_names:
        ctx.error(
            f"duplicate subscription {name_str!r} multi_id={multi_id} (A records)", off
        )
    if name_str not in formats:
        ctx.error(
            f"add-logged (A) references undefined format {name_str!r} "
            "(format/subscription mismatch)",
            off,
        )
        return
    subscriptions[msg_id] = formats[name_str]
    sub_names.add((name_str, multi_id))
