import struct

from df2ulog import ulog_codec as C
from df2ulog import ulog_lint as L
from df2ulog.ulog_writer import UlogWriter


def _minimal(path):
    with open(path, "wb") as f:
        w = UlogWriter(f, 0)
        w.write_flag_bits()
        fmt = C.UlogFormat(
            "ATT",
            (
                C.UlogField("uint64_t", 1, "timestamp"),
                C.UlogField("float", 1, "Roll"),
            ),
        )
        w.write_format(fmt)
        w.write_add_logged(0, "ATT", 0)
        w.write_data(0, struct.pack("<Qf", 1000, 1.5))
        w.write_sync()


def _records(data):
    out, off = [], 16
    while off + 3 <= len(data):
        size, typ = struct.unpack_from("<HB", data, off)
        out.append((off, size, typ))
        off += 3 + size
    return out


def mutate_ulog_file(path, mutation: str) -> None:
    data = bytearray(path.read_bytes())
    recs = _records(data)
    if mutation == "bad_magic":
        data[0] ^= 0xFF
    elif mutation == "short_header":
        data = data[:10]
    elif mutation == "missing_B":
        off, size, _typ = recs[0]
        data = data[:off] + data[off + 3 + size :]
    elif mutation == "B_size_39":
        off, _size, _typ = recs[0]
        payload = bytes(data[off + 3 : off + 3 + 39])
        data = bytearray(
            data[:off] + struct.pack("<HB", 39, ord("B")) + payload + data[off + 3 + 40 :]
        )
    elif mutation == "B_incompat_nonzero":
        off, _size, _typ = recs[0]
        data[off + 3 + 8] = 1
    elif mutation == "F_after_A":
        f_off, f_size, _ = next(r for r in recs if r[2] == ord("F"))
        a_off, a_size, _ = next(r for r in recs if r[2] == ord("A"))
        f_rec = bytes(data[f_off : f_off + 3 + f_size])
        a_rec = bytes(data[a_off : a_off + 3 + a_size])
        data[f_off : f_off + 3 + f_size] = a_rec
        data[a_off : a_off + 3 + a_size] = f_rec
    elif mutation == "A_without_F":
        a_off, a_size, _ = next(r for r in recs if r[2] == ord("A"))
        name_off = a_off + 3 + 3
        name_len = a_size - 3
        data[name_off : name_off + name_len] = b"Z" * name_len
    elif mutation == "D_without_A":
        d_off, _d_size, _ = next(r for r in recs if r[2] == ord("D"))
        struct.pack_into("<H", data, d_off + 3, 200)
    elif mutation == "D_short_payload":
        d_off, d_size, _ = next(r for r in recs if r[2] == ord("D"))
        keep = 3 + d_size - 1
        new = data[:d_off] + struct.pack("<HB", d_size - 1, ord("D")) + data[d_off + 3 : d_off + keep] + data[d_off + 3 + d_size :]
        data = bytearray(new)
    elif mutation == "D_long_payload":
        d_off, d_size, _ = next(r for r in recs if r[2] == ord("D"))
        new = (
            data[:d_off]
            + struct.pack("<HB", d_size + 1, ord("D"))
            + data[d_off + 3 : d_off + 3 + d_size]
            + b"\x00"
            + data[d_off + 3 + d_size :]
        )
        data = bytearray(new)
    elif mutation == "nonmonotonic_ts":
        d_off, d_size, _ = next(r for r in recs if r[2] == ord("D"))
        d_rec = bytes(data[d_off : d_off + 3 + d_size])
        dup = bytearray(d_rec)
        struct.pack_into("<Q", dup, 3 + 2, 500)
        insert_at = d_off + 3 + d_size
        data = bytearray(data[:insert_at] + dup + data[insert_at:])
    elif mutation == "S_size_16":
        s_off, _s_size, _ = next(r for r in recs if r[2] == ord("S"))
        data = bytearray(
            data[:s_off]
            + struct.pack("<HB", 16, ord("S"))
            + C.SYNC_BYTES
            + b"\x00" * 8
            + data[s_off + 3 + 8 :]
        )
    elif mutation == "truncated_record":
        data = data[:-2]
    else:  # pragma: no cover - programming error in the test
        raise AssertionError(f"unknown mutation {mutation}")
    path.write_bytes(bytes(data))


def test_valid_file(tmp_path):
    p = tmp_path / "a.ulg"
    _minimal(p)
    r = L.lint_ulog(p)
    assert r.ok and not r.errors(), [i.message for i in r.errors()]
    assert r.stats["D"] == 1 and r.stats["topics"] == 1
    assert r.stats["B"] == 1 and r.stats["F"] == 1 and r.stats["A"] == 1
    assert r.stats["S"] == 1
    assert r.stats["first_ts_us"] == 1000 and r.stats["last_ts_us"] == 1000


def test_detects_corruptions(tmp_path):
    cases = [
        ("bad_magic", "magic"),
        ("short_header", "header"),
        ("missing_B", "flag"),
        ("B_size_39", "flag"),
        ("B_incompat_nonzero", "incompat"),
        ("A_without_F", "format"),
        ("F_after_A", "order"),
        ("D_without_A", "subscription"),
        ("D_short_payload", "length"),
        ("D_long_payload", "length"),
        ("nonmonotonic_ts", "monotonic"),
        ("S_size_16", "sync"),
        ("truncated_record", "truncated"),
    ]
    for mutation, keyword in cases:
        p = tmp_path / f"{mutation}.ulg"
        _minimal(p)
        mutate_ulog_file(p, mutation)
        r = L.lint_ulog(p)
        assert not r.ok, mutation
        assert any(keyword in i.message.lower() for i in r.errors()), (
            mutation,
            [i.message for i in r.errors()],
        )


def test_lint_missing_file(tmp_path):
    r = L.lint_ulog(tmp_path / "nope.ulg")
    assert not r.ok and r.errors()
