"""DataFlash source adapter and self-built metadata registry (plan §4.4, ADR-10).

pymavlink's per-message ``fmt.units`` / ``fmt.instance_field`` are NOT trusted:
in text mode they are lost (plan §2.2.12) and FMTU/UNIT/MULT may arrive after
the first data records (plan §2.2.6).  A full-file pass A rebuilds everything.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pymavlink import DFReader

from .errors import (
    DataFlashReadError,
    InputFormatError,
    UnsupportedFormatCharError,
)
from .unit_tables import GPS_LEAP_SECONDS, MULT_TO_PREFIX

SourceFormat = Literal["binary", "text"]

# Width in bytes of every DataFlash format character (pymavlink FORMAT_TO_STRUCT).
DF_STRUCT_WIDTHS: dict[str, int] = {
    "a": 64,
    "b": 1,
    "B": 1,
    "h": 2,
    "H": 2,
    "i": 4,
    "I": 4,
    "q": 8,
    "Q": 8,
    "f": 4,
    "d": 8,
    "g": 2,
    "n": 4,
    "N": 16,
    "Z": 64,
    "c": 2,
    "C": 2,
    "e": 4,
    "E": 4,
    "L": 4,
    "M": 1,
}

_HEAD1 = 0xA3
_HEAD2 = 0x95

_FIRMWARE_RE = re.compile(r"^(?:ArduCopter|ArduPlane|ArduRover|ArduSub|Blimp)\b.*")
_BOARD_RE = re.compile(r"^FC-\S.*")
_FRAME_RE = re.compile(r"Frame:\s*(.+?)\s*$")

_SCALED_CHARS = frozenset("cCeELM")


def _format_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def detect_format(path: Path) -> SourceFormat:
    """Detect binary vs Mission-Planner-text DataFlash by content (not name)."""
    path = Path(path)
    try:
        with path.open("rb") as fp:
            head = fp.read(4096)
    except OSError as exc:
        raise InputFormatError(f"cannot read input {path}: {exc}") from exc
    if not head:
        raise InputFormatError(f"input file is empty: {path}")
    if head[:2] == bytes([_HEAD1, _HEAD2]) or bytes([_HEAD1, _HEAD2]) in head[:64]:
        return "binary"
    try:
        with path.open("rb") as fp:
            chunk = fp.read(65536)
    except OSError as exc:
        raise InputFormatError(f"cannot read input {path}: {exc}") from exc
    if "FMT," in chunk.decode("utf-8", errors="replace"):
        return "text"
    raise InputFormatError(
        f"unrecognised DataFlash input (neither binary 0xA3 0x95 frames nor "
        f"'FMT,' text lines): {path}"
    )


@dataclass(frozen=True)
class DfFormatSpec:
    type_id: int
    length: int
    name: str
    format_chars: str
    columns: tuple[str, ...]

    def expected_length(self) -> int:
        """FMT.Length (which includes the 3-byte frame header) from format chars."""
        return 3 + sum(DF_STRUCT_WIDTHS[c] for c in self.format_chars)

    def payload_widths(self) -> tuple[int, ...]:
        return tuple(DF_STRUCT_WIDTHS[c] for c in self.format_chars)


@dataclass
class MetadataScan:
    source_format: SourceFormat
    df_message_count: int
    formats: dict[int, DfFormatSpec]
    unit_lookup: dict[str, str]
    mult_lookup: dict[str, float]
    fmtu: dict[int, tuple[str, str]]
    params: dict[str, float]
    param_conflicts: dict[str, list[float]]
    firmware: str | None
    board: str | None
    frame: str | None
    gps_week: int | None
    gps_ms: int | None
    gps_utc: str | None
    rtc_utc: str | None
    meta_counts: dict[str, int]
    redefinitions: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class DataFlashRegistry:
    formats: dict[int, DfFormatSpec]
    name_to_type: dict[str, int]
    instance_column: dict[int, int | None]
    fmtu: dict[int, tuple[str, str]]
    unit_lookup: dict[str, str]
    mult_lookup: dict[str, float]

    def format_by_name(self, name: str) -> DfFormatSpec | None:
        type_id = self.name_to_type.get(name)
        if type_id is None:
            return None
        return self.formats.get(type_id)

    def instance_column_index(self, type_id: int) -> int | None:
        return self.instance_column.get(type_id)

    def units_for(self, type_id: int) -> list[str]:
        spec = self.formats.get(type_id)
        if spec is None:
            return []
        fmtu = self.fmtu.get(type_id)
        if fmtu is None:
            return [""] * len(spec.columns)
        unit_ids, mult_ids = fmtu
        out: list[str] = []
        for i in range(len(spec.columns)):
            label = self.unit_lookup.get(unit_ids[i], "") if i < len(unit_ids) else ""
            if not label:
                out.append("")
                continue
            df_char = spec.format_chars[i] if i < len(spec.format_chars) else ""
            mult = self.mult_lookup.get(mult_ids[i]) if i < len(mult_ids) else None
            if mult is not None and df_char not in _SCALED_CHARS:
                if mult in MULT_TO_PREFIX:
                    out.append(MULT_TO_PREFIX[mult] + label)
                else:
                    out.append(f"{mult:.4g} {label}")
            else:
                out.append(label)
        return out


class DataFlashSource:
    """Thin, exception-normalising wrapper around pymavlink's DFReader."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        if not self._path.is_file():
            raise InputFormatError(f"input file not found: {self._path}")
        self._format = detect_format(self._path)
        self._closed = False
        self._unparsed_tail_bytes = 0
        try:
            if self._format == "binary":
                self._reader: Any = DFReader.DFReader_binary(str(self._path))
            else:
                self._reader = DFReader.DFReader_text(str(self._path))
        except Exception as exc:
            raise _wrap_reader_error(self._path, exc) from exc

    @property
    def path(self) -> Path:
        return self._path

    @property
    def source_format(self) -> SourceFormat:
        return self._format

    @property
    def mav_type(self) -> int:
        return int(getattr(self._reader, "mav_type", 0) or 0)

    @property
    def unparsed_tail_bytes(self) -> int:
        return self._unparsed_tail_bytes

    def iter_messages(self) -> Iterator[Any]:
        if self._closed:
            raise DataFlashReadError(f"{self._path.name}: source is closed")
        try:
            self._reader.rewind()
        except Exception as exc:
            raise DataFlashReadError(
                f"{self._path.name}: failed to rewind reader: {exc}"
            ) from exc
        while True:
            try:
                msg = self._reader.recv_msg()
            except Exception as exc:
                raise DataFlashReadError(
                    f"{self._path.name}: read failed: {exc}", context=str(exc)
                ) from exc
            if msg is None:
                break
            yield msg
        self._update_tail()

    def _update_tail(self) -> None:
        if self._format != "binary":
            self._unparsed_tail_bytes = 0
            return
        try:
            data_len = int(self._reader.data_len)
            offset = int(self._reader.offset)
        except (AttributeError, TypeError, ValueError):
            self._unparsed_tail_bytes = 0
            return
        self._unparsed_tail_bytes = max(0, data_len - offset)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._reader.close()
        except Exception:  # noqa: BLE001, S110 - best-effort cleanup
            pass

    def __enter__(self) -> DataFlashSource:  # noqa: PYI034 - keep 3.10 compatibility
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _wrap_reader_error(path: Path, exc: Exception) -> Exception:
    message = str(exc)
    if "Unsupported format char" in message:
        match = re.search(r"Unsupported format char: '(.+?)' in message (\S+)", message)
        char = match.group(1) if match else ""
        name = match.group(2) if match else None
        return UnsupportedFormatCharError(
            f"{path.name}: {message}", char=char, message_name=name
        )
    return DataFlashReadError(f"{path.name}: {message}")


# ---------------------------------------------------------------------------
# pass A: metadata
# ---------------------------------------------------------------------------


def _msg_to_spec(msg: Any) -> DfFormatSpec | None:
    """Build a DfFormatSpec from an FMT message; None when the record is unusable."""
    try:
        type_id = int(msg.Type)
        length = int(msg.Length)
        name = str(msg.Name).replace("\x00", "")
        format_chars = str(msg.Format).replace("\x00", "")
        columns_raw = str(msg.Columns).replace("\x00", "")
    except (AttributeError, TypeError, ValueError):
        return None
    if not format_chars or not name:
        return None
    columns = tuple(col for col in columns_raw.split(",") if col)
    if len(columns) != len(format_chars):
        return None
    if any(c not in DF_STRUCT_WIDTHS for c in format_chars):
        return None
    return DfFormatSpec(
        type_id=type_id,
        length=length,
        name=name,
        format_chars=format_chars,
        columns=columns,
    )


def scan_metadata(
    source: DataFlashSource,
) -> tuple[MetadataScan, DataFlashRegistry]:
    formats: dict[int, DfFormatSpec] = {}
    unit_lookup: dict[str, str] = {}
    mult_lookup: dict[str, float] = {}
    fmtu: dict[int, tuple[str, str]] = {}
    params: dict[str, float] = {}
    param_conflicts: dict[str, list[float]] = {}
    meta_counts: dict[str, int] = {}
    warnings: list[str] = []
    redefinitions = 0
    count = 0
    firmware: str | None = None
    board: str | None = None
    frame: str | None = None
    gps_week: int | None = None
    gps_ms: int | None = None
    gps_utc: str | None = None
    rtc_utc: str | None = None
    ver_fws: str | None = None

    for msg in source.iter_messages():
        count += 1
        try:
            type_name = msg.get_type()
        except Exception:  # noqa: BLE001, S112 - defensive against odd messages
            continue
        meta_counts[type_name] = meta_counts.get(type_name, 0) + 1

        if type_name == "FMT":
            spec = _msg_to_spec(msg)
            if spec is None:
                warnings.append(
                    f"FMT record skipped (bad columns/format): {getattr(msg, 'Name', '?')!r}"
                )
                continue
            if spec.type_id in formats:
                redefinitions += 1
            if spec.expected_length() != spec.length:
                warnings.append(
                    f"FMT {spec.name!r}: Length {spec.length} != expected "
                    f"{spec.expected_length()}; type skipped"
                )
                continue
            formats[spec.type_id] = spec
        elif type_name == "FMTU":
            try:
                ftype = int(msg.FmtType)
                unit_ids = str(msg.UnitIds).replace("\x00", "")
                mult_ids = str(msg.MultIds).replace("\x00", "")
            except (AttributeError, TypeError, ValueError):
                warnings.append("FMTU record skipped (unreadable fields)")
                continue
            if ftype not in formats:
                warnings.append(f"FMTU references unknown FmtType {ftype}")
            fmtu[ftype] = (unit_ids, mult_ids)
        elif type_name == "UNIT":
            try:
                unit_id = int(msg.Id) & 0xFF
                label = str(msg.Label).replace("\x00", "")
            except (AttributeError, TypeError, ValueError):
                warnings.append("UNIT record skipped (unreadable fields)")
                continue
            unit_lookup[chr(unit_id)] = label
        elif type_name == "MULT":
            try:
                mult_id = int(msg.Id) & 0xFF
                mult = float(f"{float(msg.Mult):.7g}")
            except (AttributeError, TypeError, ValueError):
                warnings.append("MULT record skipped (unreadable fields)")
                continue
            mult_lookup[chr(mult_id)] = mult
        elif type_name == "PARM":
            try:
                pname = str(msg.Name).replace("\x00", "")
                value = float(msg.Value)
            except (AttributeError, TypeError, ValueError):
                continue
            if not pname:
                continue
            if pname not in params:
                params[pname] = value
            elif params[pname] != value:
                param_conflicts.setdefault(pname, []).append(value)
        elif type_name == "MSG":
            text = str(getattr(msg, "Message", "")).replace("\x00", "").strip()
            if firmware is None and _FIRMWARE_RE.match(text):
                firmware = text
            if board is None and _BOARD_RE.match(text):
                board = text
            if frame is None:
                m = _FRAME_RE.search(text)
                if m:
                    frame = m.group(1).strip()
        elif type_name == "VER":
            fws = str(getattr(msg, "FWS", "")).replace("\x00", "").strip()
            if fws:
                ver_fws = fws
        elif type_name == "GPS":
            if gps_week is None:
                try:
                    week = int(msg.GWk)
                    ms = int(msg.GMS)
                except (AttributeError, TypeError, ValueError):
                    continue
                if week > 0 and ms > 0:
                    gps_week = week
                    gps_ms = ms
                    epoch = datetime(1980, 1, 6, tzinfo=timezone.utc)
                    utc = epoch + timedelta(weeks=week, milliseconds=ms)
                    utc -= timedelta(seconds=GPS_LEAP_SECONDS)
                    gps_utc = _format_utc(utc)
        elif type_name == "RTC":
            if rtc_utc is None:
                try:
                    epoch_s = int(msg.Epoch)
                    dt = datetime.fromtimestamp(epoch_s, tz=timezone.utc)
                except (AttributeError, TypeError, ValueError, OSError, OverflowError):
                    continue
                if 2000 <= dt.year <= 2100:
                    rtc_utc = _format_utc(dt)

    if firmware is None and ver_fws:
        firmware = ver_fws

    name_to_type: dict[str, int] = {}
    for type_id in sorted(formats):
        name_to_type[formats[type_id].name] = type_id
    instance_column: dict[int, int | None] = {}
    for type_id, spec in formats.items():
        idx: int | None = None
        fmtu_entry = fmtu.get(type_id)
        if fmtu_entry is not None:
            found = fmtu_entry[0].find("#")
            if 0 <= found < len(spec.columns):
                idx = found
        instance_column[type_id] = idx

    registry = DataFlashRegistry(
        formats=formats,
        name_to_type=name_to_type,
        instance_column=instance_column,
        fmtu=fmtu,
        unit_lookup=unit_lookup,
        mult_lookup=mult_lookup,
    )
    scan = MetadataScan(
        source_format=source.source_format,
        df_message_count=count,
        formats=formats,
        unit_lookup=unit_lookup,
        mult_lookup=mult_lookup,
        fmtu=fmtu,
        params=params,
        param_conflicts=param_conflicts,
        firmware=firmware,
        board=board,
        frame=frame,
        gps_week=gps_week,
        gps_ms=gps_ms,
        gps_utc=gps_utc,
        rtc_utc=rtc_utc,
        meta_counts=meta_counts,
        redefinitions=redefinitions,
        warnings=warnings,
    )
    return scan, registry


def extract_timestamp_us(msg: Any, spec: DfFormatSpec) -> int | None:
    """DataFlash timestamp in microseconds: TimeUS, else TimeMS*1000, else None."""
    if "TimeUS" in spec.columns:
        value = getattr(msg, "TimeUS", None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    if "TimeMS" in spec.columns:
        value = getattr(msg, "TimeMS", None)
        if value is not None:
            try:
                return int(value) * 1000
            except (TypeError, ValueError):
                return None
    return None
