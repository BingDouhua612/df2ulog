import hashlib
import json
import struct

import pytest
import pyulog
from fixtures.make_fixtures import (
    make_arrays_fixture,
    make_instance_fixture,
    make_minimal_fixture,
    make_time_clamp_fixture,
    make_time_reset_fixture,
    make_truncated_fixture,
    make_unknown_char_fixture,
    write_binary_log,
)

from df2ulog.converter import (
    ConversionOptions,
    WriteCounters,
    build_conversion_plan,
    convert_file,
    iter_output_records,
)
from df2ulog.df_source import DataFlashSource
from df2ulog.errors import (
    Df2UlogError,
    OutputExistsError,
    TimeOrderError,
    UnsupportedFormatCharError,
)
from df2ulog.ulog_lint import lint_ulog


def test_convert_minimal_binary(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "out.ulg"
    res = convert_file(fx.bin_path, ConversionOptions(output=out))
    u = pyulog.ULog(str(out))
    assert not u.file_corruption
    assert lint_ulog(out).ok
    assert res.output_sha256 == hashlib.sha256(out.read_bytes()).hexdigest()
    assert res.source_sha256 == hashlib.sha256(fx.bin_path.read_bytes()).hexdigest()
    assert res.data_record_count == sum(res.topic_counts.values())
    assert res.info_records >= 4
    assert res.params_written == 2
    assert res.logging_records == 5
    assert len(u.initial_parameters) == 2
    assert len(u.logged_messages) == 5
    assert res.df_message_count == 35


def test_convert_minimal_text(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "out_text.ulg"
    res = convert_file(fx.log_path, ConversionOptions(output=out))
    assert res.source_format == "text"
    u = pyulog.ULog(str(out))
    assert not u.file_corruption
    assert lint_ulog(out).ok
    assert res.data_record_count == 6
    names = {(d.name, d.multi_id) for d in u.data_list}
    assert names == {("MINI", 0), ("MIN2", 0), ("GPS", 0)}


def test_deterministic(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    a, b = tmp_path / "a.ulg", tmp_path / "b.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=a))
    convert_file(fx.bin_path, ConversionOptions(output=b))
    assert a.read_bytes() == b.read_bytes()


def test_instance_multi_id(tmp_path):
    fx = make_instance_fixture(tmp_path)
    out = tmp_path / "i.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=out))
    u = pyulog.ULog(str(out))
    assert {(d.name, d.multi_id) for d in u.data_list} == {("INST", 0), ("INST", 1)}
    assert lint_ulog(out).ok


def test_arrays_and_layout(tmp_path):
    fx = make_arrays_fixture(tmp_path)
    out = tmp_path / "a.ulg"
    res = convert_file(fx.bin_path, ConversionOptions(output=out))
    plan = next(p for p in res.topics if p.df_name == "ISBD")
    assert plan.payload_size == 8 + 2 + 2 + 3 * 64
    assert "int16_t[32]" in plan.ulog_format.format_string()
    assert lint_ulog(out).ok
    raw = out.read_bytes()
    recs, off = [], 16
    while off + 3 <= len(raw):
        size, typ = struct.unpack_from("<HB", raw, off)
        recs.append((off, size, typ))
        off += 3 + size
    d_recs = [r for r in recs if r[2] == ord("D")]
    assert d_recs and all(r[1] == 2 + 204 for r in d_recs)


def test_output_guard_and_cleanup(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    out.write_bytes(b"x")
    with pytest.raises(OutputExistsError):
        convert_file(fx.bin_path, ConversionOptions(output=out))
    convert_file(fx.bin_path, ConversionOptions(output=out, force=True))
    assert out.exists() and not (tmp_path / "o.ulg.part").exists()
    assert lint_ulog(out).ok


def test_no_data_topic(tmp_path):
    defs = {
        0x80: ("FMT", "BBnNZ", "Type,Length,Name,Format,Columns"),
        32: ("PARM", "QNff", "TimeUS,Name,Value,Default"),
    }
    p = tmp_path / "nodata.bin"
    write_binary_log(p, defs, [(32, [1000, "P1", 1.0, float("nan")])])
    with pytest.raises(Df2UlogError):
        convert_file(p, ConversionOptions(output=tmp_path / "nd.ulg"))
    assert not (tmp_path / "nd.ulg").exists()
    assert not (tmp_path / "nd.ulg.part").exists()


def test_unknown_char_explicit_failure(tmp_path):
    fx = make_unknown_char_fixture(tmp_path)
    with pytest.raises(UnsupportedFormatCharError):
        convert_file(fx.bin_path, ConversionOptions(output=tmp_path / "u.ulg"))
    assert not (tmp_path / "u.ulg").exists()


def test_truncated_tail_is_reported(tmp_path):
    fx = make_truncated_fixture(tmp_path)
    res = convert_file(fx.bin_path, ConversionOptions(output=tmp_path / "tr.ulg"))
    assert res.source_tail_bytes > 0
    assert any("source_tail_bytes" in w for w in res.warnings)


def test_time_clamp(tmp_path):
    fx = make_time_clamp_fixture(tmp_path)
    res = convert_file(fx.bin_path, ConversionOptions(output=tmp_path / "t.ulg"))
    assert sum(res.topic_nudged.values()) > 0
    assert lint_ulog(tmp_path / "t.ulg").ok


def test_time_reset(tmp_path):
    fx = make_time_reset_fixture(tmp_path)
    with pytest.raises(TimeOrderError):
        convert_file(fx.bin_path, ConversionOptions(output=tmp_path / "t2.ulg"))
    assert not (tmp_path / "t2.ulg").exists()
    assert not (tmp_path / "t2.ulg.part").exists()
    res = convert_file(
        fx.bin_path,
        ConversionOptions(output=tmp_path / "t3.ulg", allow_time_reset=True),
    )
    assert res.warnings, "allow-time-reset 必须留下高危警告"
    assert sum(res.topic_nudged.values()) == 1
    assert lint_ulog(tmp_path / "t3.ulg").ok


def test_params_modes(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    none_out = tmp_path / "none.ulg"
    res_none = convert_file(
        fx.bin_path, ConversionOptions(output=none_out, params_mode="none")
    )
    assert res_none.params_written == 0
    assert pyulog.ULog(str(none_out)).initial_parameters == {}
    init_out = tmp_path / "init.ulg"
    res_init = convert_file(fx.bin_path, ConversionOptions(output=init_out))
    assert res_init.params_written == 2
    params = pyulog.ULog(str(init_out)).initial_parameters
    assert set(params) == {"TEST_PARAM", "TEST_PARAM2"}


def test_no_logging(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "nolog.ulg"
    res = convert_file(fx.bin_path, ConversionOptions(output=out, keep_logging=False))
    assert res.logging_records == 0
    assert pyulog.ULog(str(out)).logged_messages == []


def test_iter_output_records_matches_convert_file(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    options = ConversionOptions(output=tmp_path / "same.ulg")
    with DataFlashSource(fx.bin_path) as source:
        plan = build_conversion_plan(source, options)
        counters = WriteCounters()
        records = list(iter_output_records(source, plan, options, counters))
    res = convert_file(fx.bin_path, ConversionOptions(output=tmp_path / "same2.ulg"))
    assert len([r for r in records if r.kind == "data"]) == res.data_record_count
    assert counters.logging_records == res.logging_records
    assert counters.topic_counts == res.topic_counts
    assert counters.topic_first_ts == res.topic_first_ts


def test_report_json_written(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out, rep = tmp_path / "r.ulg", tmp_path / "r.json"
    res = convert_file(
        fx.bin_path, ConversionOptions(output=out, report_json=rep)
    )
    assert out.exists() and rep.exists()
    report = json.loads(rep.read_text(encoding="utf-8"))
    assert report["schema_version"] == 1
    assert report["source"]["sha256"] == res.source_sha256
    assert report["output"]["sha256"] == res.output_sha256
    assert report["counts"]["data_records"] == res.data_record_count
    assert report["counts"]["topics"] == len(res.topics)
    assert report["counts"]["params"] == 2
    keys = [(t["ulog_name"], t["multi_id"]) for t in report["topics"]]
    assert keys == sorted(keys)
    for topic in report["topics"]:
        assert all(f["name"] != "timestamp" for f in topic["fields"])


def test_progress_callback_monotonic(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "p.ulg"
    calls: list[tuple[str, int]] = []
    res = convert_file(
        fx.bin_path,
        ConversionOptions(output=out),
        progress_callback=lambda phase, pct: calls.append((phase, pct)),
    )
    assert res.data_record_count == 6
    assert calls[0][1] == 0
    assert calls[-1] == ("done", 100)
    percentages = [pct for _phase, pct in calls]
    assert percentages == sorted(percentages), percentages
    phases = {phase for phase, _pct in calls}
    assert {"scan", "planned", "definitions", "write", "done"} <= phases
    assert out.exists()
