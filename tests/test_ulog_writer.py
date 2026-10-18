import io
import struct

import pytest

from df2ulog import ulog_codec as C
from df2ulog.errors import UlogWriteError
from df2ulog.ulog_writer import UlogWriter


def test_header_written_immediately():
    buf = io.BytesIO()
    UlogWriter(buf, 123456)
    assert buf.getvalue() == C.ULOG_MAGIC + b"\x01" + struct.pack("<Q", 123456)


def test_flag_bits_record():
    buf = io.BytesIO()
    w = UlogWriter(buf, 0)
    w.write_flag_bits()
    w.flush()
    data = buf.getvalue()[16:]
    assert data[:3] == struct.pack("<HB", 40, ord("B"))
    assert data[3:] == b"\x00" * 40
    assert w.counts["B"] == 1


def test_info_char_no_nul():
    buf = io.BytesIO()
    w = UlogWriter(buf, 0)
    w.write_info("ver_sw", "abc")
    w.flush()
    rec = buf.getvalue()[16:]
    assert rec[:3] == struct.pack("<HB", 18, ord("I"))
    assert rec[3:] == b"\x0e" + b"char[3] ver_sw" + b"abc"


def test_info_utf8_and_key_sanitized():
    buf = io.BytesIO()
    w = UlogWriter(buf, 0)
    w.write_info("my key", "中")
    w.flush()
    rec = buf.getvalue()[16:]
    key = b"char[3] my_key"
    payload = bytes([len(key)]) + key + "中".encode()
    assert rec == struct.pack("<HB", len(payload), ord("I")) + payload


def test_parameter_and_format_and_add():
    buf = io.BytesIO()
    w = UlogWriter(buf, 0)
    fmt = C.UlogFormat(
        "ATT",
        (
            C.UlogField("uint64_t", 1, "timestamp"),
            C.UlogField("float", 1, "Roll"),
        ),
    )
    w.write_initial_parameter("P1", 1.5)
    w.write_format(fmt)
    w.write_add_logged(7, "ATT", 0)
    w.flush()
    data = buf.getvalue()[16:]
    p_payload = b"\x08" + b"float P1" + struct.pack("<f", 1.5)
    assert data[:3] == struct.pack("<HB", len(p_payload), ord("P"))
    assert data[3 : 3 + len(p_payload)] == p_payload
    off = 3 + len(p_payload)
    fs = fmt.format_string().encode()
    assert data[off : off + 3] == struct.pack("<HB", len(fs), ord("F"))
    assert data[off + 3 : off + 3 + len(fs)] == fs
    off += 3 + len(fs)
    assert data[off : off + 3] == struct.pack("<HB", 6, ord("A"))
    assert data[off + 3 : off + 9] == struct.pack("<BH", 0, 7) + b"ATT"


def test_data_and_logging_and_sync():
    buf = io.BytesIO()
    w = UlogWriter(buf, 0)
    w.write_data(3, struct.pack("<Qf", 1000, 1.5))
    w.write_logging(2000, "hello")
    w.write_sync()
    w.flush()
    data = buf.getvalue()[16:]
    assert data[:3] == struct.pack("<HB", 2 + 8 + 4, ord("D"))
    assert data[3:5] == struct.pack("<H", 3)
    off = 3 + 2 + 8 + 4
    log_text = b"hello"
    assert data[off : off + 3] == struct.pack("<HB", 9 + len(log_text), ord("L"))
    assert data[off + 3 : off + 12] == struct.pack("<BQ", ord("6"), 2000)
    off += 3 + 9 + len(log_text)
    assert data[off : off + 3] == struct.pack("<HB", 8, ord("S"))
    assert data[off + 3 : off + 11] == C.SYNC_BYTES
    assert w.counts == {"D": 1, "L": 1, "S": 1}


def test_rejects_invalid():
    buf = io.BytesIO()
    w = UlogWriter(buf, 0)
    with pytest.raises(UlogWriteError):
        w.write_add_logged(0, "A" * 300, 0)
    with pytest.raises(UlogWriteError):
        w.write_add_logged(0, "X", 300)
    with pytest.raises(UlogWriteError):
        w.write_data(0, b"\x00")
    with pytest.raises(UlogWriteError):
        w.write_logging(0, "x", level="9")
