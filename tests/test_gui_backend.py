
import pytest
from fixtures.make_fixtures import (
    make_minimal_fixture,
    make_unknown_char_fixture,
)

from df2ulog.errors import InputFormatError
from df2ulog.gui.backend import (
    ConversionRequest,
    describe_source,
    output_path_for,
    run_conversion,
)


def test_describe_source(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    info = describe_source(fx.bin_path)
    assert info.source_format == "binary"
    assert info.size > 0
    assert describe_source(fx.log_path).source_format == "text"
    with pytest.raises(InputFormatError):
        describe_source(tmp_path / "nope.BIN")


def test_output_path_for(tmp_path):
    src = tmp_path / "a.BIN"
    assert output_path_for(ConversionRequest(source=src)).name == "a.ulg"
    out_dir = tmp_path / "out"
    assert (
        output_path_for(ConversionRequest(source=src, output_dir=out_dir))
        == out_dir / "a.ulg"
    )
    assert (
        output_path_for(ConversionRequest(source=src, output_name="x.custom"))
        == src.parent / "x.custom.ulg"
    )


def test_run_conversion_success_with_progress(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out_dir = tmp_path / "out"
    calls = []
    outcome = run_conversion(
        ConversionRequest(source=fx.bin_path, output_dir=out_dir),
        progress=lambda phase, pct: calls.append((phase, pct)),
    )
    assert outcome.ok, outcome.message
    assert outcome.error_code == 0
    assert outcome.output_path == out_dir / "minimal.ulg"
    assert outcome.output_path.exists()
    assert outcome.result is not None and outcome.result.data_record_count == 6
    assert calls[-1] == ("done", 100)


def test_run_conversion_refuses_existing_output(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / "minimal.ulg"
    existing.write_bytes(b"keep-me")
    outcome = run_conversion(ConversionRequest(source=fx.bin_path, output_dir=out_dir))
    assert not outcome.ok
    assert outcome.error_code == 6
    assert existing.read_bytes() == b"keep-me"


def test_run_conversion_overwrite_and_reports(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "minimal.ulg").write_bytes(b"old")
    outcome = run_conversion(
        ConversionRequest(
            source=fx.bin_path,
            output_dir=out_dir,
            overwrite=True,
            report_json=True,
            verify=True,
        )
    )
    assert outcome.ok, outcome.message
    assert outcome.verify_ok is True
    assert outcome.report_json_path is not None
    assert outcome.report_json_path.exists()
    assert outcome.output_path is not None
    assert outcome.output_path.read_bytes()[:7] == b"ULog\x01\x12\x35"


def test_run_conversion_invalid_input(tmp_path):
    outcome = run_conversion(ConversionRequest(source=tmp_path / "missing.BIN"))
    assert not outcome.ok
    assert outcome.error_code == 3


def test_run_conversion_unknown_char(tmp_path):
    fx = make_unknown_char_fixture(tmp_path)
    outcome = run_conversion(ConversionRequest(source=fx.bin_path))
    assert not outcome.ok
    assert outcome.error_code == 4


def test_scan_params_without_conversion(tmp_path):
    from df2ulog.gui.backend import scan_params

    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "should_not_exist.ulg"
    outcome = scan_params(fx.bin_path)
    assert outcome.ok
    assert outcome.result is not None
    assert outcome.result.source_format == "binary"
    assert [name for name, _v, _t in outcome.result.param_changes] == [
        "TEST_PARAM",
        "TEST_PARAM2",
    ]
    assert not out.exists()
