import subprocess
import sys
import textwrap

import df2ulog


def run_module(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "df2ulog.gui", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    )


def test_version_headless():
    r = run_module("--version")
    assert r.returncode == 0, r.stderr
    assert df2ulog.__version__ in r.stdout


def test_headless_import_does_not_import_qt():
    code = textwrap.dedent(
        """
        import sys
        from df2ulog.gui.__main__ import main
        assert main(["--version"]) == 0
        assert "PySide6" not in sys.modules, "headless path must not import PySide6"
        print("HEADLESS_OK")
        """
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    assert "HEADLESS_OK" in r.stdout


def test_selftest_converts_headlessly(tmp_path):
    from fixtures.make_fixtures import make_minimal_fixture

    fx = make_minimal_fixture(tmp_path)
    out_dir = tmp_path / "out"
    r = run_module("--selftest", str(fx.bin_path), "-o", str(out_dir))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert (out_dir / "minimal.ulg").exists()
    assert "转换完成" in r.stdout


def test_selftest_reports_error_exit_code(tmp_path):
    r = run_module("--selftest", str(tmp_path / "missing.BIN"))
    assert r.returncode == 3, (r.stdout, r.stderr)
