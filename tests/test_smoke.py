import subprocess
import sys

import pyulog
from pymavlink import DFReader

import df2ulog


def test_version():
    assert df2ulog.__version__ == "0.1.0"


def test_pymavlink_surface():
    assert DFReader.DFReader_binary is not None
    assert DFReader.DFReader_text is not None
    assert callable(DFReader.DFReader_is_text_log)


def test_pyulog_surface():
    assert hasattr(pyulog, "ULog")


def test_module_version_cli():
    r = subprocess.run(
        [sys.executable, "-m", "df2ulog", "--version"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert r.returncode == 0 and "0.1.0" in r.stdout
