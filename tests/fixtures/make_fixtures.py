"""Synthetic DataFlash fixtures (plan §6.1).

Binary fixtures store the *raw* (unscaled) values that pymavlink applies its
implicit multipliers to; text fixtures store the physical values, exactly like
Mission Planner's text export.  The manifest always records physical values so
both formats can be asserted against the same expectations.

This package is imported by the tests only; it is not part of the shipped tool.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

# Same table as pymavlink DFReader (plan §6.1).
DF_STRUCT = {
    "a": "64s",
    "b": "b",
    "B": "B",
    "h": "h",
    "H": "H",
    "i": "i",
    "I": "I",
    "q": "q",
    "Q": "Q",
    "f": "f",
    "d": "d",
    "g": "e",
    "n": "4s",
    "N": "16s",
    "Z": "64s",
    "c": "h",
    "C": "H",
    "e": "i",
    "E": "I",
    "L": "i",
    "M": "b",
}

CHAR_WIDTH = {"n": 4, "N": 16, "Z": 64}

FMT_TYPE_ID = 0x80
FMTU_TYPE_ID = 116
UNIT_TYPE_ID = 117
MULT_TYPE_ID = 118

_HEAD = b"\xa3\x95"

# (type_id, name, format, columns) metadata definitions shared by the fixtures.
META_DEFS: dict[int, tuple[str, str, str]] = {
    0x80: ("FMT", "BBnNZ", "Type,Length,Name,Format,Columns"),
    116: ("FMTU", "QBNN", "TimeUS,FmtType,UnitIds,MultIds"),
    117: ("UNIT", "QbZ", "TimeUS,Id,Label"),
    118: ("MULT", "Qbd", "TimeUS,Id,Mult"),
    32: ("PARM", "QNff", "TimeUS,Name,Value,Default"),
    59: ("MSG", "QBBZ", "TimeUS,ID,Seq,Message"),
    121: ("MODE", "QMBB", "TimeUS,Mode,ModeNum,Rsn"),
    182: ("EV", "QB", "TimeUS,Id"),
    208: (
        "VER",
        "QBHBBBBIZHBBII",
        "TimeUS,BT,BST,Maj,Min,Pat,FWT,GH,FWS,APJ,BU,FV,IMI,ICI",
    ),
    130: (
        "GPS",
        "QBBIHBcLLeffffB",
        "TimeUS,I,Status,GMS,GWk,NSats,HDop,Lat,Lng,Alt,Spd,GCrs,VZ,Yaw,U",
    ),
    2: ("RTC", "QQB", "TimeUS,Epoch,SourceType"),
}


@dataclass
class Fixture:
    bin_path: Path
    log_path: Path | None
    manifest: dict


def format_length(fmt: str) -> int:
    """DF FMT.Length = 3-byte frame header + packed payload."""
    return 3 + struct.calcsize("<" + "".join(DF_STRUCT[c] for c in fmt))


def frame(type_id: int, payload: bytes) -> bytes:
    return _HEAD + bytes([type_id]) + payload


def _fmt_payload(type_id: int, name: str, fmt: str, columns: str, length: int) -> bytes:
    return struct.pack(
        "<BB4s16s64s",
        type_id,
        length,
        name.encode("ascii"),
        fmt.encode("ascii"),
        columns.encode("ascii"),
    )


def _char_bytes(value, width: int) -> bytes:
    if isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = bytes(value)
    return raw[:width].ljust(width, b"\x00")


def _to_array_bytes(value) -> bytes:
    values = list(value)
    if len(values) < 32:
        values = values + [0] * (32 - len(values))
    elif len(values) > 32:
        values = values[:32]
    return struct.pack("<32h", *(int(v) for v in values))


def _binary_storage(char: str, value) -> object:
    """Convert a physical value to the raw value stored in a .BIN frame."""
    if char == "a":
        if isinstance(value, (bytes, bytearray)):
            return bytes(value).ljust(64, b"\x00")[:64]
        return _to_array_bytes(value)
    if char in CHAR_WIDTH:
        return _char_bytes(value, CHAR_WIDTH[char])
    if char == "M":
        raw = int(value) & 0xFF
        return raw - 256 if raw > 127 else raw
    if char in ("c", "C", "e", "E"):
        return round(float(value) * 100)
    if char == "L":
        return round(float(value) * 1e7)
    if char in ("f", "d", "g"):
        return float(value)
    return int(value)


def _text_value(char: str, value) -> str:
    if char == "a":
        if isinstance(value, str):
            return value
        return "[" + " ".join(str(int(v)) for v in value) + "]"
    if char in CHAR_WIDTH:
        return str(value)
    if char == "M":
        if isinstance(value, str):
            return value
        return str(int(value))
    if char in ("c", "C", "e", "E", "L", "f", "d", "g"):
        return repr(float(value))
    return str(int(value))


def _fmt_line(type_id: int, name: str, fmt: str, columns: str, length: int) -> str:
    return f"FMT, {type_id}, {length}, {name}, {fmt}, {columns}"


def write_binary_log(path, defs, messages) -> Path:
    """Write a synthetic binary DataFlash log.

    defs: {type_id: (name, format, columns[, length])}
    messages: [(type_id, [physical values...]), ...]
    """
    path = Path(path)
    all_defs = dict(defs)
    if FMT_TYPE_ID not in all_defs:
        all_defs[FMT_TYPE_ID] = META_DEFS[FMT_TYPE_ID]
    out = bytearray()
    ordered = [FMT_TYPE_ID] + [tid for tid in all_defs if tid != FMT_TYPE_ID]
    lengths: dict[int, int] = {}
    for tid in ordered:
        entry = all_defs[tid]
        name, fmt, columns = entry[0], entry[1], entry[2]
        length = entry[3] if len(entry) > 3 else format_length(fmt)
        lengths[tid] = length
        out += frame(FMT_TYPE_ID, _fmt_payload(tid, name, fmt, columns, length))
    for tid, values in messages:
        name, fmt, columns = all_defs[tid][0], all_defs[tid][1], all_defs[tid][2]
        if len(values) != len(fmt):
            raise ValueError(
                f"message {name}: {len(values)} values for format {fmt!r}"
            )
        storage = [_binary_storage(c, v) for c, v in zip(fmt, values)]
        out += frame(tid, struct.pack("<" + "".join(DF_STRUCT[c] for c in fmt), *storage))
    path.write_bytes(bytes(out))
    return path


def write_text_log(path, defs, messages, *, interleave: bool = True) -> Path:
    """Write a synthetic Mission-Planner-style text DataFlash log."""
    path = Path(path)
    all_defs = dict(defs)
    if FMT_TYPE_ID not in all_defs:
        all_defs[FMT_TYPE_ID] = META_DEFS[FMT_TYPE_ID]
    lengths = {
        tid: (entry[3] if len(entry) > 3 else format_length(entry[1]))
        for tid, entry in all_defs.items()
    }

    lines: list[str] = []
    written: set[int] = set()

    def emit_fmt(tid: int) -> None:
        if tid in written:
            return
        name, fmt, columns = all_defs[tid][0], all_defs[tid][1], all_defs[tid][2]
        lines.append(_fmt_line(tid, name, fmt, columns, lengths[tid]))
        written.add(tid)

    if not interleave:
        for tid in [FMT_TYPE_ID] + [t for t in all_defs if t != FMT_TYPE_ID]:
            emit_fmt(tid)
    else:
        emit_fmt(FMT_TYPE_ID)

    for tid, values in messages:
        name, fmt, _columns = all_defs[tid][0], all_defs[tid][1], all_defs[tid][2]
        if len(values) != len(fmt):
            raise ValueError(
                f"message {name}: {len(values)} values for format {fmt!r}"
            )
        if interleave:
            emit_fmt(tid)
        text_values = [_text_value(c, v) for c, v in zip(fmt, values)]
        lines.append(name + ", " + ", ".join(text_values))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


# ---------------------------------------------------------------------------
# F1: minimal.bin + minimal.log
# ---------------------------------------------------------------------------

MINI_TYPE = 200
MIN2_TYPE = 201
MINI_FMT = "QfBiZ"
MINI_COLUMNS = "TimeUS,X,Y,I,tag"
MIN2_FMT = "QLLc"
MIN2_COLUMNS = "TimeUS,Lat,Lng,HDop"

FIRMWARE = "ArduCopter V4.7.1 (2004b70c)"
BOARD = "FC-A6H7 00510033 3533510C 31373632"
FRAME = "QUAD/X"
GPS_WEEK = 2440
GPS_MS = 113296300
GPS_UTC = "2026-10-12T07:27:58.300000Z"
PARAMS = {"TEST_PARAM": 1.5, "TEST_PARAM2": 2.25}


def _minimal_defs() -> dict[int, tuple[str, str, str]]:
    defs = dict(META_DEFS)
    defs[MINI_TYPE] = ("MINI", MINI_FMT, MINI_COLUMNS)
    defs[MIN2_TYPE] = ("MIN2", MIN2_FMT, MIN2_COLUMNS)
    return defs


def _minimal_messages() -> list[tuple[int, list]]:
    t = 1_000_000
    mini = [
        [t, 1.5, 7, 111, "abc"],
        [t + 1_000, -2.25, 255, -222, "xy"],
        [t + 2_000, 3.25, 0, 333, "z"],
    ]
    mini2 = [
        [t + 500, 47.5, 8.25, 0.5],
        [t + 1_500, -47.25, -8.75, -1.25],
    ]
    meta: list[tuple[int, list]] = [
        (59, [t + 10, 39, 0, FIRMWARE]),
        (59, [t + 11, 40, 0, BOARD]),
        (59, [t + 12, 41, 0, f"Frame: {FRAME}"]),
        (
            208,
            [t + 13, 1, 255, 4, 7, 1, 1, 0x2004B70C, FIRMWARE, 0, 2, 0, 0, 0],
        ),
        (2, [t + 14, 1730000000, 0]),
        (32, [t + 20, "TEST_PARAM", PARAMS["TEST_PARAM"], float("nan")]),
        (32, [t + 21, "TEST_PARAM2", PARAMS["TEST_PARAM2"], float("nan")]),
        (182, [t + 30, 10]),
        (121, [t + 40, 2, 2, 1]),
        (
            130,
            [
                t + 50,
                0,
                3,
                GPS_MS,
                GPS_WEEK,
                12,
                0.5,
                47.5,
                8.25,
                100.0,
                3.5,
                0.0,
                0.0,
                0.0,
                1,
            ],
        ),
    ]
    # UNIT / MULT definitions then FMTU (deliberately after the data topics so
    # the self-built registry is exercised, cf. plan §2.2.12).
    units = [
        (t + 60, ord("s"), "s"),
        (t + 61, ord("A"), "A"),
        (t + 62, ord("U"), "V"),
    ]
    mults = [(t + 70, ord("0"), 1.0), (t + 71, ord("B"), 100.0)]
    fmtus = [
        (t + 80, MINI_TYPE, "sA--", "F0--"),
        (t + 81, MIN2_TYPE, "s---", "F---"),
    ]
    data: list[tuple[int, list]] = []
    data += [(MINI_TYPE, v) for v in mini]
    data += [(MIN2_TYPE, v) for v in mini2]
    data += [(UNIT_TYPE_ID, v) for v in units]
    data += [(MULT_TYPE_ID, v) for v in mults]
    data += [(FMTU_TYPE_ID, v) for v in fmtus]
    return meta + data


def make_minimal_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = _minimal_defs()
    messages = _minimal_messages()
    bin_path = write_binary_log(tmp_path / "minimal.bin", defs, messages)
    log_path = write_text_log(tmp_path / "minimal.log", defs, messages, interleave=True)
    t = 1_000_000
    manifest = {
        "firmware": FIRMWARE,
        "board": BOARD,
        "frame": FRAME,
        "gps_week": GPS_WEEK,
        "gps_ms": GPS_MS,
        "gps_utc": GPS_UTC,
        "params": dict(PARAMS),
        "data_message_count": 5,
        "MINI": {"X": 1.5, "Y": 7, "I": 111, "tag": "abc", "timestamp": t},
        "MIN2": {"Lat": 47.5, "Lng": 8.25, "HDop": 0.5, "timestamp": t + 500},
    }
    return Fixture(bin_path=bin_path, log_path=log_path, manifest=manifest)


# ---------------------------------------------------------------------------
# F2: all_chars.bin (appendix A, all 21 format characters; FMT.Format is
# char[16] so the 21 characters are split over two message types)
# ---------------------------------------------------------------------------

ALLA_TYPE = 210
ALLA_FMT = "QabBhHiIqfdgnNZ"
ALLA_COLUMNS = "TimeUS,a,b,B,h,H,i,I,q,f,d,g,n,N,Z"
ALLB_TYPE = 211
ALLB_FMT = "QcCeELM"
ALLB_COLUMNS = "TimeUS,c,C,e,E,L,M"

ALL_A = [i - 16 for i in range(32)]
ALLA_VALUES = {
    "TimeUS": 1_000_000,
    "a": ALL_A,
    "b": -5,
    "B": 200,
    "h": -3000,
    "H": 60000,
    "i": -100000,
    "I": 4000000000,
    "q": -5000000000,
    "f": 1.5,
    "d": 2.25,
    "g": 0.5,
    "n": "ab",
    "N": "hello",
    "Z": "world",
}
ALLB_VALUES = {
    "TimeUS": 2_000_000,
    "c": 1.23,
    "C": 2.34,
    "e": -3.45,
    "E": 4.56,
    "L": 47.1234567,
    "M": 200,
}


def make_all_chars_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = dict(META_DEFS)
    defs[ALLA_TYPE] = ("ALLA", ALLA_FMT, ALLA_COLUMNS)
    defs[ALLB_TYPE] = ("ALLB", ALLB_FMT, ALLB_COLUMNS)
    messages = [
        (ALLA_TYPE, [ALLA_VALUES[c] for c in ALLA_COLUMNS.split(",")]),
        (ALLB_TYPE, [ALLB_VALUES[c] for c in ALLB_COLUMNS.split(",")]),
    ]
    bin_path = write_binary_log(tmp_path / "all_chars.bin", defs, messages)
    manifest = {
        "ALLA": dict(ALLA_VALUES),
        "ALLB": dict(ALLB_VALUES),
        # ULog payload sizes: 'g' and c/C/e/E widen to float32, L to double, so
        # these are not just the DF frame widths.
        "ALLA_payload_size": 194,
        "ALLB_payload_size": 33,
    }
    return Fixture(bin_path=bin_path, log_path=None, manifest=manifest)


# ---------------------------------------------------------------------------
# F3: instances.bin + instances.log  (INST with an instance column)
# ---------------------------------------------------------------------------

INST_TYPE = 202
INST_FMT = "QBf"
INST_COLUMNS = "TimeUS,Instance,Val"


def _instance_defs() -> dict[int, tuple[str, str, str]]:
    defs = dict(META_DEFS)
    defs[INST_TYPE] = ("INST", INST_FMT, INST_COLUMNS)
    return defs


def _instance_messages() -> list[tuple[int, list]]:
    t = 2_000_000
    messages: list[tuple[int, list]] = [
        (INST_TYPE, [t, 0, 1.0]),
        (INST_TYPE, [t + 100, 1, 2.0]),
        (INST_TYPE, [t + 200, 0, 3.0]),
        (INST_TYPE, [t + 300, 1, 4.0]),
    ]
    messages += [
        (UNIT_TYPE_ID, [t + 400, ord("s"), "s"]),
        (UNIT_TYPE_ID, [t + 401, ord("E"), "V"]),
        (MULT_TYPE_ID, [t + 410, ord("0"), 1.0]),
        (FMTU_TYPE_ID, [t + 420, INST_TYPE, "s#E", "F-0"]),
    ]
    return messages


def make_instance_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = _instance_defs()
    messages = _instance_messages()
    bin_path = write_binary_log(tmp_path / "instances.bin", defs, messages)
    log_path = write_text_log(tmp_path / "instances.log", defs, messages)
    manifest = {
        "INST": {"Instance": 0, "Val": 1.0, "timestamp": 2_000_000},
        "instance_column": 1,
    }
    return Fixture(bin_path=bin_path, log_path=log_path, manifest=manifest)


# ---------------------------------------------------------------------------
# F6: meta_late.bin (FMTU/UNIT/MULT all after the data)
# ---------------------------------------------------------------------------

LATE_TYPE = 203
LATE_FMT = "QBf"
LATE_COLUMNS = "TimeUS,Instance,Val"


def make_meta_late_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = dict(META_DEFS)
    defs[LATE_TYPE] = ("LATE", LATE_FMT, LATE_COLUMNS)
    t = 3_000_000
    messages: list[tuple[int, list]] = [
        (LATE_TYPE, [t, 0, 1.5]),
        (LATE_TYPE, [t + 100, 1, 2.5]),
        (UNIT_TYPE_ID, [t + 200, ord("s"), "s"]),
        (UNIT_TYPE_ID, [t + 201, ord("E"), "V"]),
        (MULT_TYPE_ID, [t + 210, ord("0"), 1.0]),
        (FMTU_TYPE_ID, [t + 220, LATE_TYPE, "s#E", "F-0"]),
    ]
    bin_path = write_binary_log(tmp_path / "meta_late.bin", defs, messages)
    manifest = {"instance_column": 1, "LATE": {"Instance": 0, "Val": 1.5}}
    return Fixture(bin_path=bin_path, log_path=None, manifest=manifest)


# ---------------------------------------------------------------------------
# F7: text_late_meta.log (interleaved FMT definitions, FMTU after data)
# ---------------------------------------------------------------------------


def make_text_late_meta_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = _instance_defs()
    messages = _instance_messages()
    log_path = write_text_log(tmp_path / "text_late_meta.log", defs, messages)
    manifest = {"instance_column": 1}
    return Fixture(bin_path=log_path, log_path=log_path, manifest=manifest)


# ---------------------------------------------------------------------------
# F4: arrays_chars.bin (ISBD: three 32-element int16 arrays; D payload 204 B)
# ---------------------------------------------------------------------------

ISBD_TYPE = 220
ISBD_FMT = "QHHaaa"
ISBD_COLUMNS = "TimeUS,N,seqno,x,y,z"
ISBD_X = [1] * 32
ISBD_Y = [2] * 32
ISBD_Z = [3] * 32


def make_arrays_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = dict(META_DEFS)
    defs[ISBD_TYPE] = ("ISBD", ISBD_FMT, ISBD_COLUMNS)
    t = 4_000_000
    zeros = [0] * 32
    messages = [
        (ISBD_TYPE, [t, 0, 1, ISBD_X, ISBD_Y, ISBD_Z]),
        (ISBD_TYPE, [t + 100, 0, 2, zeros, [1] * 32, [2] * 32]),
    ]
    bin_path = write_binary_log(tmp_path / "arrays.bin", defs, messages)
    manifest = {
        "ISBD": {"N": 0, "seqno": 1, "x": ISBD_X, "y": ISBD_Y, "z": ISBD_Z},
        "payload_size": 8 + 2 + 2 + 3 * 64,
    }
    return Fixture(bin_path=bin_path, log_path=None, manifest=manifest)


# ---------------------------------------------------------------------------
# F5: times_clamp.bin / times_reset.bin
# ---------------------------------------------------------------------------

TCLK_TYPE = 230
TCLK_FMT = "QH"
TCLK_COLUMNS = "TimeUS,Val"


def make_time_clamp_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = dict(META_DEFS)
    defs[TCLK_TYPE] = ("TCLK", TCLK_FMT, TCLK_COLUMNS)
    base = 1_000_000
    messages = [
        (TCLK_TYPE, [base, 1]),
        (TCLK_TYPE, [base, 2]),          # duplicate timestamp -> +1 us
        (TCLK_TYPE, [base - 500, 3]),    # small backwards jump -> +1 us
        (TCLK_TYPE, [base + 1, 4]),      # still <= last -> +1 us
    ]
    bin_path = write_binary_log(tmp_path / "times_clamp.bin", defs, messages)
    return Fixture(bin_path=bin_path, log_path=None, manifest={"nudged": 3})


def make_time_reset_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = dict(META_DEFS)
    defs[TCLK_TYPE] = ("TCLK", TCLK_FMT, TCLK_COLUMNS)
    messages = [
        (TCLK_TYPE, [10_000_000, 1]),
        (TCLK_TYPE, [5_000_000, 2]),  # > 1 s backwards jump
    ]
    bin_path = write_binary_log(tmp_path / "times_reset.bin", defs, messages)
    return Fixture(bin_path=bin_path, log_path=None, manifest={"reset": True})


# ---------------------------------------------------------------------------
# F8: unknown_char.bin (FMT with an unsupported format character 'X')
# ---------------------------------------------------------------------------


def make_unknown_char_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = {
        FMT_TYPE_ID: META_DEFS[FMT_TYPE_ID],
        5: ("BADF", "QfX", "TimeUS,Val,Bad", 20),
    }
    bin_path = write_binary_log(tmp_path / "unknown_char.bin", defs, [])
    return Fixture(bin_path=bin_path, log_path=None, manifest={})


# ---------------------------------------------------------------------------
# F9: truncated.bin (last data frame cut in the middle)
# ---------------------------------------------------------------------------

TRNC_TYPE = 240
TRNC_FMT = "Qf"
TRNC_COLUMNS = "TimeUS,Val"


def make_truncated_fixture(tmp_path) -> Fixture:
    tmp_path = Path(tmp_path)
    defs = dict(META_DEFS)
    defs[TRNC_TYPE] = ("TRNC", TRNC_FMT, TRNC_COLUMNS)
    p = write_binary_log(
        tmp_path / "truncated.bin",
        defs,
        [(TRNC_TYPE, [1000, 1.0]), (TRNC_TYPE, [2000, 2.0])],
    )
    raw = p.read_bytes()
    p.write_bytes(raw[:-2])
    return Fixture(bin_path=p, log_path=None, manifest={"tail_bytes": 10})
