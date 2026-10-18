import json
import struct

import pyulog
from fixtures.make_fixtures import (
    make_all_chars_fixture,
    make_instance_fixture,
    make_minimal_fixture,
)

from df2ulog.converter import ConversionOptions, convert_file
from df2ulog.verifier import VerifyOptions, verify_ulog


def _records(path):
    """Return (file_bytes, [(record_offset, msg_size, msg_type), ...]); skips 16 B header."""
    data = path.read_bytes()
    out, off = [], 16
    while off + 3 <= len(data):
        size, typ = struct.unpack("<HB", data[off : off + 3])
        out.append((off, size, typ))
        off += 3 + size
    return data, out


def test_verify_valid(tmp_path):
    fx = make_all_chars_fixture(tmp_path)
    out, rep = tmp_path / "o.ulg", tmp_path / "r.json"
    convert_file(fx.bin_path, ConversionOptions(output=out, report_json=rep))
    res = verify_ulog(
        VerifyOptions(ulg_path=out, source_path=fx.bin_path, report_json=rep)
    )
    assert res.ok, res.failures()
    names = [c.name for c in res.checks]
    assert any("lint" in name for name in names)
    assert any("pyulog" in name for name in names)
    assert any("replay" in name or "source" in name for name in names)


def test_verify_minimal_and_instances(tmp_path):
    for maker in (make_minimal_fixture, make_instance_fixture):
        fixture_dir = tmp_path / maker.__name__
        fixture_dir.mkdir()
        fx = maker(fixture_dir)
        out = tmp_path / f"{maker.__name__}.ulg"
        convert_file(fx.bin_path, ConversionOptions(output=out))
        res = verify_ulog(VerifyOptions(ulg_path=out, source_path=fx.bin_path))
        assert res.ok, (maker.__name__, res.failures())


def test_verify_detects_field_corruption(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=out))
    data, recs = _records(out)
    d_recs = [r for r in recs if r[2] == ord("D")]
    assert len(d_recs) >= 2
    off, size, _typ = d_recs[1]
    buf = bytearray(data)
    buf[off + 3 + size - 1] ^= 0x01  # flip the last payload byte (length unchanged)
    out.write_bytes(bytes(buf))
    res = verify_ulog(VerifyOptions(ulg_path=out, source_path=fx.bin_path))
    assert not res.ok, "翻转字段值后 verify 必须检出"


def test_verify_detects_dropped_record(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=out))
    data, recs = _records(out)
    off, size, _typ = next(r for r in recs if r[2] == ord("D"))
    out.write_bytes(data[:off] + data[off + 3 + size :])
    res = verify_ulog(VerifyOptions(ulg_path=out, source_path=fx.bin_path))
    assert not res.ok, "删掉一条 D 记录后 verify 必须检出"


def test_verify_report_only(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out, rep = tmp_path / "o.ulg", tmp_path / "r.json"
    convert_file(fx.bin_path, ConversionOptions(output=out, report_json=rep))
    res = verify_ulog(VerifyOptions(ulg_path=out, report_json=rep))
    assert res.ok, res.failures()


def test_verify_report_only_detects_count_mismatch(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out, rep = tmp_path / "o.ulg", tmp_path / "r.json"
    convert_file(fx.bin_path, ConversionOptions(output=out, report_json=rep))
    report = json.loads(rep.read_text(encoding="utf-8"))
    report["counts"]["data_records"] += 1
    rep.write_text(json.dumps(report), encoding="utf-8")
    res = verify_ulog(VerifyOptions(ulg_path=out, report_json=rep))
    assert not res.ok


def test_verify_source_mismatch(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    other = make_all_chars_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=out))
    res = verify_ulog(VerifyOptions(ulg_path=out, source_path=other.bin_path))
    assert not res.ok, "源与输出不匹配时 verify 必须失败"


def test_verify_without_source_or_report_only_checks_lint_and_pyulog(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=out))
    res = verify_ulog(VerifyOptions(ulg_path=out))
    assert res.ok
    assert len(res.checks) == 2


def test_verify_detects_lint_error(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    convert_file(fx.bin_path, ConversionOptions(output=out))
    data = bytearray(out.read_bytes())
    data[0] ^= 0xFF
    out.write_bytes(bytes(data))
    res = verify_ulog(VerifyOptions(ulg_path=out))
    assert not res.ok
    assert any("lint" in c.name for c in res.checks if not c.ok)


def test_verify_restores_options_from_report_json(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out, rep = tmp_path / "o.ulg", tmp_path / "r.json"
    convert_file(
        fx.bin_path,
        ConversionOptions(output=out, report_json=rep, params_mode="none"),
    )
    u = pyulog.ULog(str(out))
    assert u.initial_parameters == {}
    res = verify_ulog(
        VerifyOptions(ulg_path=out, source_path=fx.bin_path, report_json=rep)
    )
    assert res.ok, res.failures()


def test_verify_missing_file_returns_failure(tmp_path):
    res = verify_ulog(VerifyOptions(ulg_path=tmp_path / "missing.ulg"))
    assert not res.ok
    assert any(not check.ok for check in res.checks)
