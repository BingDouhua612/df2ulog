import numpy as np
import pytest
import pyulog
from conftest import REAL_LOGS
from fixtures.make_fixtures import make_minimal_fixture, make_text_late_meta_fixture

from df2ulog.converter import ConversionOptions, convert_file
from df2ulog.ulog_lint import lint_ulog
from df2ulog.verifier import VerifyOptions, verify_ulog


def test_text_fixture_roundtrip(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "t.ulg"
    res = convert_file(fx.log_path, ConversionOptions(output=out))
    assert res.source_format == "text"
    assert res.source_tail_bytes == 0
    u = pyulog.ULog(str(out))
    assert not u.file_corruption
    assert lint_ulog(out).ok
    assert res.data_record_count == 6
    assert res.params_written == 2
    assert res.logging_records == 5
    assert verify_ulog(VerifyOptions(ulg_path=out, source_path=fx.log_path)).ok


def test_text_late_meta_instance_survives(tmp_path):
    fx = make_text_late_meta_fixture(tmp_path)
    res = convert_file(fx.log_path, ConversionOptions(output=tmp_path / "r.ulg"))
    names = {(t.ulog_name, t.multi_id) for t in res.topics}
    assert ("INST", 0) in names and ("INST", 1) in names
    assert res.data_record_count == 4
    assert verify_ulog(
        VerifyOptions(ulg_path=tmp_path / "r.ulg", source_path=fx.log_path)
    ).ok


def test_text_minimal_values_match_binary(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "text.ulg"
    convert_file(fx.log_path, ConversionOptions(output=out))
    u = pyulog.ULog(str(out))
    mini = u.get_dataset("MINI", 0)
    assert float(mini.data["X"][0]) == pytest.approx(1.5, abs=1e-6)
    assert int(mini.data["Y"][0]) == 7
    assert int(mini.data["I"][0]) == 111
    mini2 = u.get_dataset("MIN2", 0)
    assert float(mini2.data["Lat"][0]) == pytest.approx(47.5, abs=1e-6)
    assert float(mini2.data["Lng"][0]) == pytest.approx(8.25, abs=1e-6)
    assert float(mini2.data["HDop"][0]) == pytest.approx(0.5, abs=1e-6)


@pytest.mark.real
def test_real_text_log(tmp_path):
    path = REAL_LOGS.get("log_ref")
    if path is None or not path.exists():
        pytest.skip("no local real log (configure tests/real_logs.local.json)")
    out, rep = tmp_path / "real.ulg", tmp_path / "real.json"
    res = convert_file(path, ConversionOptions(output=out, report_json=rep))
    assert res.source_format == "text"
    assert res.data_record_count > 0
    assert res.topics
    assert lint_ulog(out).ok
    assert verify_ulog(
        VerifyOptions(ulg_path=out, source_path=path, report_json=rep)
    ).ok


@pytest.mark.real
def test_cross_format_consistency(tmp_path):
    bin_path = REAL_LOGS.get("bin_ref")
    log_path = REAL_LOGS.get("log_ref")
    if bin_path is None or log_path is None:
        pytest.skip("no local real logs (configure tests/real_logs.local.json)")
    if not bin_path.exists() or not log_path.exists():
        pytest.skip("local real logs not found")
    out_bin, out_log = tmp_path / "b.ulg", tmp_path / "l.ulg"
    rb = convert_file(bin_path, ConversionOptions(output=out_bin))
    rl = convert_file(log_path, ConversionOptions(output=out_log))
    kb = {(p.ulog_name, p.multi_id) for p in rb.topics}
    kl = {(p.ulog_name, p.multi_id) for p in rl.topics}
    assert kb == kl
    assert kb

    # counts: identical except the text log has exactly one extra PIDP record
    for key in kb:
        diff = rl.topic_counts[key] - rb.topic_counts[key]
        assert diff == (1 if key == ("PIDP", 0) else 0), key
    # first/last timestamps: identical except PIDP (text last record 51,430,142 us)
    for key in kb:
        if key == ("PIDP", 0):
            continue
        assert rb.topic_first_ts[key] == rl.topic_first_ts[key], key
        assert rb.topic_last_ts[key] == rl.topic_last_ts[key], key

    # sampled field values: equal within text-precision tolerance
    ub, ul = pyulog.ULog(str(out_bin)), pyulog.ULog(str(out_log))
    for name in ("ATT", "IMU", "GPS", "RATE"):
        db, dl = ub.get_dataset(name, 0), ul.get_dataset(name, 0)
        for field in db.data:
            if field == "timestamp":
                continue
            vb, vl = db.data[field], dl.data[field]
            n = min(len(vb), len(vl))
            assert np.allclose(
                vb[:n], vl[:n], rtol=1e-6, atol=1e-6, equal_nan=True
            ), (name, field)
    # determinism across formats for the shared 99-topic set is covered above
