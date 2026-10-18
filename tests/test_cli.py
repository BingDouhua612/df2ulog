import shutil
import subprocess
import sys

import pyulog
from fixtures.make_fixtures import make_minimal_fixture


def run(*args, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "df2ulog", *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=cwd,
    )


def test_help_and_version():
    assert run("--help").returncode == 0
    r = run("--version")
    assert r.returncode == 0 and "0.1.0" in r.stdout


def test_convert_verify_inspect(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out, rep = tmp_path / "o.ulg", tmp_path / "r.json"
    r = run(str(fx.bin_path), "-o", str(out), "--report-json", str(rep))
    assert r.returncode == 0 and out.exists() and rep.exists()
    r = run(
        "verify", str(out), "--source", str(fx.bin_path), "--report-json", str(rep)
    )
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "PASS" in r.stdout.upper()
    r = run("inspect", str(fx.bin_path))
    assert r.returncode == 0 and "topic" in r.stdout.lower()


def test_default_output_and_exit_codes(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    assert run(str(fx.bin_path)).returncode == 0
    assert (fx.bin_path.parent / f"{fx.bin_path.stem}.ulg").exists()
    assert run(str(fx.bin_path)).returncode == 6  # output already exists
    assert run(str(tmp_path / "missing.BIN")).returncode == 3
    assert run("verify", str(tmp_path / "missing.ulg")).returncode == 5
    assert run(str(fx.bin_path), "--params", "bogus").returncode == 2


def test_force_and_dry_run(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    assert run(str(fx.bin_path), "-o", str(out), "--dry-run").returncode == 0
    assert not out.exists()
    assert run(str(fx.bin_path), "-o", str(out)).returncode == 0
    assert run(str(fx.bin_path), "-o", str(out)).returncode == 6
    assert run(str(fx.bin_path), "-o", str(out), "--force").returncode == 0


def test_quiet_params_none_no_logging(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    r = run(
        str(fx.bin_path), "-o", str(out), "-q", "--params", "none", "--no-logging"
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""
    u = pyulog.ULog(str(out))
    assert u.initial_parameters == {}
    assert u.logged_messages == []


def test_verify_failure_exit_code(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    assert run(str(fx.bin_path), "-o", str(out)).returncode == 0
    data = bytearray(out.read_bytes())
    data[0] ^= 0xFF
    out.write_bytes(bytes(data))
    r = run("verify", str(out))
    assert r.returncode == 5
    assert "FAIL" in (r.stdout + r.stderr).upper()


def test_inline_verify(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    r = run(str(fx.bin_path), "-o", str(out), "--verify", "--report-json", str(tmp_path / "r.json"))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "PASS" in r.stdout.upper()


def test_inspect_limit_and_content(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    r = run("inspect", str(fx.bin_path), "--limit", "2")
    assert r.returncode == 0
    assert "format" in r.stdout.lower()
    assert "binary" in r.stdout.lower()
    assert "MINI" in r.stdout or "GPS" in r.stdout
    assert "more topic" in r.stdout.lower()


def test_chinese_and_space_path(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    directory = tmp_path / "中文 目录"
    directory.mkdir()
    src = directory / "日志 样本.bin"
    shutil.copy(fx.bin_path, src)
    out = directory / "输出 文件.ulg"
    r = run(str(src), "-o", str(out), "--verify")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert out.exists()


def test_strict_mode_on_clean_fixture(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "o.ulg"
    assert run(str(fx.bin_path), "-o", str(out), "--strict").returncode == 0


def test_convert_text_report(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out, txt = tmp_path / "o.ulg", tmp_path / "report.txt"
    r = run(str(fx.bin_path), "-o", str(out), "--report", str(txt))
    assert r.returncode == 0 and txt.exists()
    assert "df2ulog" in txt.read_text(encoding="utf-8")


def test_unknown_format_char_exit_4(tmp_path):
    from fixtures.make_fixtures import make_unknown_char_fixture

    fx = make_unknown_char_fixture(tmp_path)
    r = run(str(fx.bin_path), "-o", str(tmp_path / "u.ulg"))
    assert r.returncode == 4
