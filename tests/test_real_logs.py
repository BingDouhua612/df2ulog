"""Optional acceptance tests against local real flight logs.

These tests never ship with log data: provide a JSON mapping via
``tests/real_logs.local.json`` (git-ignored) or ``DF2ULOG_REAL_LOGS_FILE``.
Without it every test here is skipped, so CI only runs the synthetic suite.

Expected roles (see ``tests/real_logs.example.json``):

- ``bin_ref`` — main DataFlash ``.BIN`` reference log;
- ``log_ref`` — Mission Planner text ``.log`` reference log;
- any additional roles (e.g. ``bin_a``, ``log_a``) are converted and checked
  for structural validity in ``test_other_real_logs_convert``.
"""

from __future__ import annotations

import pytest
import pyulog
from conftest import REAL_LOGS

from df2ulog.converter import ConversionOptions, convert_file
from df2ulog.ulog_lint import lint_ulog
from df2ulog.verifier import VerifyOptions, verify_ulog

pytestmark = pytest.mark.real


@pytest.fixture(scope="module")
def converted(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("real_acceptance")
    results: dict[str, tuple] = {}
    for role, path in REAL_LOGS.items():
        if not path.exists():
            continue
        out = out_dir / f"{role}.ulg"
        res = convert_file(path, ConversionOptions(output=out))
        results[role] = (path, res, out)
    return results


def test_reference_bin_structure(converted):
    """A real DataFlash BIN converts into a structurally valid ULog."""
    if "bin_ref" not in converted:
        pytest.skip("local real logs not found (configure tests/real_logs.local.json)")
    _path, res, out = converted["bin_ref"]
    assert res.source_format == "binary"
    assert len(res.topics) > 0
    assert res.data_record_count > 0
    assert lint_ulog(out).ok
    ulog = pyulog.ULog(str(out))
    assert not ulog.file_corruption
    assert len(ulog.data_list) == len(res.topics)


def test_reference_text_log_structure(converted):
    """A real Mission Planner text log converts into a structurally valid ULog."""
    if "log_ref" not in converted:
        pytest.skip("local real logs not found (configure tests/real_logs.local.json)")
    _path, res, out = converted["log_ref"]
    assert res.source_format == "text"
    assert len(res.topics) > 0
    assert res.data_record_count > 0
    assert lint_ulog(out).ok
    ulog = pyulog.ULog(str(out))
    assert not ulog.file_corruption


def test_other_real_logs_convert(converted):
    """Every additional local log converts and passes lint + pyulog read-back."""
    others = [role for role in converted if role not in ("bin_ref", "log_ref")]
    if not others:
        pytest.skip("no additional local real logs configured")
    for role in others:
        _path, res, out = converted[role]
        assert res.data_record_count > 0, role
        assert res.output_size > 0, role
        report = lint_ulog(out)
        assert report.ok, (role, [issue.message for issue in report.errors()])
        ulog = pyulog.ULog(str(out))
        assert not ulog.file_corruption, role
        assert len(ulog.data_list) > 0, role


def test_verify_full_replay(converted):
    """The verifier replays the whole source and reports no differences."""
    if "bin_ref" not in converted:
        pytest.skip("local real logs not found (configure tests/real_logs.local.json)")
    path, _res, out = converted["bin_ref"]
    result = verify_ulog(VerifyOptions(ulg_path=out, source_path=path))
    assert result.ok, result.failures()


def test_deterministic_output(tmp_path):
    """Converting the same input twice produces byte-identical output."""
    path = REAL_LOGS.get("bin_ref")
    if path is None or not path.exists():
        pytest.skip("local real logs not found (configure tests/real_logs.local.json)")
    first = tmp_path / "first.ulg"
    second = tmp_path / "second.ulg"
    convert_file(path, ConversionOptions(output=first))
    convert_file(path, ConversionOptions(output=second))
    assert first.read_bytes() == second.read_bytes()
