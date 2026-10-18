import struct

import pytest

from df2ulog import ulog_codec as C


def test_constants():
    assert C.ULOG_MAGIC == b"ULog\x01\x12\x35"
    assert C.ULOG_VERSION == 1
    assert C.SYNC_BYTES == bytes.fromhex("2f731320250cbb12")


def test_scalar_sizes():
    assert C.BASIC_TYPES["uint64_t"].size == 8
    assert C.BASIC_TYPES["float"].size == 4
    assert C.BASIC_TYPES["double"].alignment == 8
    assert C.BASIC_TYPES["bool"].size == 1
    assert C.SCALAR_STRUCT["uint64_t"] == "Q"
    assert len(C.BASIC_TYPES) == 11
    assert "char" not in C.BASIC_TYPES


def test_format_string_terminators():
    fmt = C.UlogFormat(
        "ATT",
        (
            C.UlogField("uint64_t", 1, "timestamp"),
            C.UlogField("float", 1, "Roll"),
        ),
    )
    assert fmt.format_string() == "ATT:uint64_t timestamp;float Roll;"
    assert fmt.payload_size() == 12


def test_char_and_array_format():
    fmt = C.UlogFormat(
        "T",
        (
            C.UlogField("uint64_t", 1, "timestamp"),
            C.UlogField("char", 4, "tag"),
            C.UlogField("int16_t", 32, "v"),
        ),
    )
    assert fmt.format_string() == "T:uint64_t timestamp;char[4] tag;int16_t[32] v;"
    assert fmt.payload_size() == 8 + 4 + 64
    fmt2 = C.UlogFormat(
        "Z",
        (
            C.UlogField("uint64_t", 1, "timestamp"),
            C.UlogField("char", 1, "flag"),
        ),
    )
    assert fmt2.format_string() == "Z:uint64_t timestamp;char[1] flag;"
    assert fmt2.payload_size() == 9


def test_size_bytes_unknown_type():
    with pytest.raises(C.UlogWriteError):
        _ = C.UlogField("nope_t", 1, "x").size_bytes


def test_sanitize():
    assert C.sanitize_name("IMU-2[0]") == "IMU_2_0_"
    assert C.sanitize_name("") == "field"
    assert C.sanitize_name("9abc") == "_9abc"
    assert len(C.sanitize_name("A" * 100)) == 63
    assert C.sanitize_name("a b/c") == "a_b_c"
    assert C.sanitize_name("ok_name") == "ok_name"


def test_pack_field():
    assert C.pack_field(C.UlogField("char", 4, "tag"), b"ab") == b"ab\x00\x00"
    assert C.pack_field(C.UlogField("char", 4, "tag"), "abcde") == b"abcd"
    assert C.pack_field(C.UlogField("uint16_t", 1, "x"), 258) == struct.pack("<H", 258)
    assert C.pack_field(C.UlogField("float", 1, "x"), 1.5) == struct.pack("<f", 1.5)
    assert C.pack_field(C.UlogField("int16_t", 2, "v"), [1, -2]) == struct.pack(
        "<2h", 1, -2
    )
    assert C.pack_field(C.UlogField("bool", 1, "b"), True) == b"\x01"
    with pytest.raises(C.UlogWriteError):
        C.pack_field(C.UlogField("uint8_t", 1, "x"), 300)
    with pytest.raises(C.UlogWriteError):
        C.pack_field(C.UlogField("int16_t", 2, "v"), [1])
