import struct
import types

import pytest
from conftest import REAL_LOGS
from fixtures.make_fixtures import (
    FMT_TYPE_ID,
    format_length,
    frame,
    make_instance_fixture,
    make_meta_late_fixture,
    make_minimal_fixture,
    write_binary_log,
)

from df2ulog.df_source import (
    DataFlashSource,
    DfFormatSpec,
    detect_format,
    extract_timestamp_us,
    scan_metadata,
)
from df2ulog.errors import InputFormatError


def test_detect_format(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    assert detect_format(fx.bin_path) == "binary"
    assert detect_format(fx.log_path) == "text"
    bogus = tmp_path / "bogus.dat"
    bogus.write_bytes(b"hello world" * 10)
    with pytest.raises(InputFormatError):
        detect_format(bogus)


def test_metadata_binary(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        scan, reg = scan_metadata(src)
    assert scan.source_format == "binary"
    spec = reg.format_by_name("MINI")
    assert spec is not None and reg.instance_column_index(spec.type_id) is None
    assert scan.meta_counts["FMTU"] >= 1
    assert scan.params["TEST_PARAM"] == pytest.approx(1.5, abs=1e-6)
    assert scan.firmware and "ArduCopter" in scan.firmware
    assert scan.gps_week == 2440 and scan.gps_ms == 113296300
    assert scan.gps_utc == "2026-10-12T07:27:58.300000Z"
    assert scan.board and scan.board.startswith("FC-")
    assert scan.frame == "QUAD/X"
    units = reg.units_for(spec.type_id)
    assert units[1] == "A"
    assert reg.units_for(reg.format_by_name("MIN2").type_id) == ["s", "", "", ""]


def test_metadata_text_late(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    with DataFlashSource(fx.log_path) as src:
        scan, reg = scan_metadata(src)
    assert scan.source_format == "text"
    assert reg.format_by_name("MINI") is not None
    assert scan.params["TEST_PARAM"] == pytest.approx(1.5, abs=1e-6)
    assert scan.firmware == "ArduCopter V4.7.1 (2004b70c)"
    assert scan.gps_week == 2440 and scan.gps_ms == 113296300


def test_instance_column_and_late_meta(tmp_path):
    fx = make_instance_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        _scan, reg = scan_metadata(src)
    inst = reg.format_by_name("INST")
    assert inst is not None and reg.instance_column_index(inst.type_id) == 1

    fx2 = make_meta_late_fixture(tmp_path)
    with DataFlashSource(fx2.bin_path) as src2:
        _scan2, reg2 = scan_metadata(src2)
    assert reg2.format_by_name("LATE") is not None
    assert reg2.instance_column_index(reg2.format_by_name("LATE").type_id) == 1


def test_iter_messages_twice_and_reopen(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        first = sum(1 for _ in src.iter_messages())
        second = sum(1 for _ in src.iter_messages())
        assert first == second
        assert first > 10
    with DataFlashSource(fx.bin_path) as src2:
        assert sum(1 for _ in src2.iter_messages()) == first


def test_fmt_redefinition_counted(tmp_path):
    fmt_fmt = ("FMT", "BBnNZ", "Type,Length,Name,Format,Columns")
    defs = {FMT_TYPE_ID: fmt_fmt, 5: ("REDF", "Qf", "TimeUS,Val")}
    messages = [(5, [1000, 1.0])]
    p = write_binary_log(tmp_path / "redef.bin", defs, messages)
    # append a second (different) FMT definition for the same type id
    fmt_payload = struct.pack(
        "<BB4s16s64s",
        5,
        format_length("Qi"),
        b"REDF",
        b"Qi",
        b"TimeUS,Val",
    )
    p.write_bytes(p.read_bytes() + frame(FMT_TYPE_ID, fmt_payload))
    with DataFlashSource(p) as src:
        scan, reg = scan_metadata(src)
    assert scan.redefinitions >= 1
    assert reg.format_by_name("REDF").format_chars == "Qi"


def test_bad_fmtu_warns_not_crash(tmp_path):
    defs = {
        FMT_TYPE_ID: ("FMT", "BBnNZ", "Type,Length,Name,Format,Columns"),
        116: ("FMTU", "QBNN", "TimeUS,FmtType,UnitIds,MultIds"),
        117: ("UNIT", "QbZ", "TimeUS,Id,Label"),
        5: ("AAA", "Qf", "TimeUS,Val"),
    }
    messages = [
        (5, [1000, 1.0]),
        (116, [1010, 250, "s", "F"]),  # unknown FmtType 250
        (117, [1020, ord("s"), "s"]),
    ]
    p = write_binary_log(tmp_path / "badfmtu.bin", defs, messages)
    with DataFlashSource(p) as src:
        scan, _reg = scan_metadata(src)
    assert scan.warnings  # unknown FMTU target is reported, not fatal
    assert 250 in scan.fmtu


def test_float16_format(tmp_path):
    defs = {
        FMT_TYPE_ID: ("FMT", "BBnNZ", "Type,Length,Name,Format,Columns"),
        5: ("HALF", "Qg", "TimeUS,Half"),
    }
    p = write_binary_log(tmp_path / "half.bin", defs, [(5, [1000, 0.5])])
    with DataFlashSource(p) as src:
        _scan, reg = scan_metadata(src)
        msgs = [m for m in src.iter_messages() if m.get_type() == "HALF"]
    (msg,) = msgs
    assert msg.Half == pytest.approx(0.5)
    assert reg.format_by_name("HALF").expected_length() == 3 + 8 + 2


def test_extract_timestamp_us():
    spec = DfFormatSpec(
        type_id=1,
        length=3 + 8 + 4,
        name="T",
        format_chars="If",
        columns=("TimeMS", "Val"),
    )
    msg = types.SimpleNamespace(TimeMS=42, Val=1.0)
    assert extract_timestamp_us(msg, spec) == 42_000
    spec2 = DfFormatSpec(
        type_id=2,
        length=3 + 8 + 4,
        name="T2",
        format_chars="Qf",
        columns=("TimeUS", "Val"),
    )
    msg2 = types.SimpleNamespace(TimeUS=1234, Val=1.0)
    assert extract_timestamp_us(msg2, spec2) == 1234
    spec3 = DfFormatSpec(
        type_id=3, length=3 + 2 + 4, name="T3", format_chars="Bf", columns=("A", "B")
    )
    assert extract_timestamp_us(types.SimpleNamespace(A=1, B=1.0), spec3) is None


# ---------------------------------------------------------------------------
# Real-log anchors (Task 4 STOP gate, plan §2.6)
# ---------------------------------------------------------------------------


@pytest.mark.real
def test_real_metadata_anchor():
    path = REAL_LOGS.get("bin_ref")
    if path is None or not path.exists():
        pytest.skip("no local real log (configure tests/real_logs.local.json)")
    with DataFlashSource(path) as src:
        scan, reg = scan_metadata(src)
    assert scan.df_message_count > 0
    assert len(scan.formats) > 0
    assert scan.meta_counts.get("FMT", 0) > 0
    assert scan.params
    imu = reg.format_by_name("IMU")
    if imu is not None:
        assert reg.instance_column_index(imu.type_id) >= 0


@pytest.mark.real
def test_real_text_metadata_anchor():
    path = REAL_LOGS.get("log_ref")
    if path is None or not path.exists():
        pytest.skip("no local real log (configure tests/real_logs.local.json)")
    with DataFlashSource(path) as src:
        scan, reg = scan_metadata(src)
    assert scan.source_format == "text"
    assert len(scan.formats) > 0
    assert reg.format_by_name("ESC") is not None
