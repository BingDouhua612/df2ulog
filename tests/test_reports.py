import json

from fixtures.make_fixtures import make_minimal_fixture

from df2ulog import __version__
from df2ulog.converter import ConversionOptions, convert_file
from df2ulog.reports import (
    REPORT_SCHEMA_VERSION,
    build_json_report,
    render_text_report,
    write_reports,
)


def _converted(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    res = convert_file(fx.bin_path, ConversionOptions(output=out))
    return fx, res


def test_json_report_schema(tmp_path):
    _fx, res = _converted(tmp_path)
    report = build_json_report(res)
    assert report["schema_version"] == REPORT_SCHEMA_VERSION == 1
    assert report["tool"]["name"] == "df2ulog"
    assert report["tool"]["version"] == __version__
    assert report["source"]["format"] == "binary"
    assert report["source"]["size"] > 0
    assert report["output"]["size"] > 0
    assert report["options"]["params_mode"] == "initial"
    assert report["options"]["keep_logging"] is True
    assert report["counts"]["df_messages"] == res.df_message_count
    assert report["counts"]["data_records"] == res.data_record_count
    assert report["counts"]["topics"] == len(res.topics)
    assert report["counts"]["df_message_types"] == 3
    assert report["counts"]["params"] == 2
    assert report["counts"]["logging_records"] == 5
    assert report["counts"]["meta_counts"]["PARM"] == 2
    assert report["time_range_us"]["first"] <= report["time_range_us"]["last"]
    assert report["firmware"] == "ArduCopter V4.7.1 (2004b70c)"
    assert report["gps_utc"] == "2026-10-12T07:27:58.300000Z"
    topic_names = {(t["ulog_name"], t["multi_id"]) for t in report["topics"]}
    assert topic_names == {("MINI", 0), ("MIN2", 0), ("GPS", 0)}
    mini = next(t for t in report["topics"] if t["ulog_name"] == "MINI")
    assert mini["count"] == 3
    assert mini["payload_size"] == 8 + 4 + 1 + 4 + 64
    assert [f["name"] for f in mini["fields"]] == ["X", "Y", "I", "tag"]
    assert mini["fields"][0]["df_char"] == "f"
    assert mini["fields"][3]["ulog_type"] == "char"
    assert mini["fields"][3]["array_len"] == 64
    json.dumps(report)  # must be JSON serialisable


def test_text_report(tmp_path):
    _fx, res = _converted(tmp_path)
    text = render_text_report(res)
    assert "df2ulog" in text
    assert "MINI" in text and "MIN2" in text
    assert str(res.data_record_count) in text
    assert "ArduCopter V4.7.1" in text


def test_write_reports_atomic(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    txt = tmp_path / "report.txt"
    rep = tmp_path / "report.json"
    res = convert_file(
        fx.bin_path,
        ConversionOptions(output=out, report_txt=txt, report_json=rep),
    )
    assert txt.exists() and rep.exists()
    assert not (tmp_path / "report.txt.part").exists()
    assert not (tmp_path / "report.json.part").exists()
    json.loads(rep.read_text(encoding="utf-8"))
    assert "df2ulog" in txt.read_text(encoding="utf-8")
    # explicit re-write is atomic and idempotent
    write_reports(res)
    assert rep.exists() and "df2ulog" in txt.read_text(encoding="utf-8")
