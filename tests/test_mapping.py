import array
import struct
from types import SimpleNamespace

import pytest
from fixtures.make_fixtures import (
    ALLA_TYPE,
    ALLB_TYPE,
    INST_TYPE,
    MINI_TYPE,
    make_all_chars_fixture,
    make_instance_fixture,
    make_minimal_fixture,
)

from df2ulog import ulog_codec as C
from df2ulog.df_source import (
    DataFlashRegistry,
    DataFlashSource,
    DfFormatSpec,
    MetadataScan,
    extract_timestamp_us,
    scan_metadata,
)
from df2ulog.mapping import (
    DF_TO_ULOG,
    FieldPlan,
    TopicStats,
    build_payload,
    build_topic_plans,
    can_map_format,
    normalize_value,
)

EXPECTED = {
    "b": "int8_t",
    "B": "uint8_t",
    "h": "int16_t",
    "H": "uint16_t",
    "i": "int32_t",
    "I": "uint32_t",
    "q": "int64_t",
    "Q": "uint64_t",
    "f": "float",
    "d": "double",
    "g": "float",
    "c": "float",
    "C": "float",
    "e": "float",
    "E": "float",
    "L": "double",
    "M": "uint8_t",
    "n": "char",
    "N": "char",
    "Z": "char",
    "a": "int16_t",
}


def _decode(plan, payload):
    out, off = {}, 0
    for f in plan.ulog_format.fields:
        if f.name == "timestamp":
            out["timestamp"] = struct.unpack_from("<Q", payload, off)[0]
        elif f.ulog_type == "char":
            out[f.name] = payload[off : off + f.size_bytes].rstrip(b"\x00").decode("utf-8")
        elif f.array_len == 1:
            out[f.name] = struct.unpack_from(
                "<" + C.SCALAR_STRUCT[f.ulog_type], payload, off
            )[0]
        else:
            out[f.name] = list(
                struct.unpack_from(
                    "<" + C.SCALAR_STRUCT[f.ulog_type] * f.array_len, payload, off
                )
            )
        off += f.size_bytes
    return out


def _registry_for(*specs) -> DataFlashRegistry:
    formats = {spec.type_id: spec for spec in specs}
    return DataFlashRegistry(
        formats=formats,
        name_to_type={spec.name: spec.type_id for spec in specs},
        instance_column={spec.type_id: None for spec in specs},
        fmtu={},
        unit_lookup={},
        mult_lookup={},
    )


def _meta_for(registry: DataFlashRegistry) -> MetadataScan:
    return MetadataScan(
        source_format="binary",
        df_message_count=1,
        formats=dict(registry.formats),
        unit_lookup={},
        mult_lookup={},
        fmtu={},
        params={},
        param_conflicts={},
        firmware=None,
        board=None,
        frame=None,
        gps_week=None,
        gps_ms=None,
        gps_utc=None,
        rtc_utc=None,
        meta_counts={},
        redefinitions=0,
    )


def _stats_for(reg, type_name, instance=None) -> dict:
    spec = reg.format_by_name(type_name)
    return {(spec.type_id, instance): TopicStats(1, 1000, 1000)}


def test_type_table_complete():
    assert set(DF_TO_ULOG) == set(EXPECTED)
    for ch, typ in EXPECTED.items():
        assert DF_TO_ULOG[ch][0] == typ
    assert DF_TO_ULOG["a"] == ("int16_t", 32)
    assert DF_TO_ULOG["n"] == ("char", 4)
    assert DF_TO_ULOG["N"] == ("char", 16)
    assert DF_TO_ULOG["Z"] == ("char", 64)


def test_instance_split(tmp_path):
    fx = make_instance_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        meta, reg = scan_metadata(src)
    tid = reg.format_by_name("INST").type_id
    assert tid == INST_TYPE
    stats = {(tid, 0): TopicStats(3, 100, 300), (tid, 1): TopicStats(2, 200, 400)}
    plans, _warnings = build_topic_plans(meta, reg, stats)
    assert {(p.ulog_name, p.multi_id) for p in plans} == {("INST", 0), ("INST", 1)}
    assert all(p.ulog_format.fields[0].name == "timestamp" for p in plans)
    assert all(p.timestamp_column == "TimeUS" for p in plans)
    assert {p.multi_id for p in plans} == {0, 1}
    assert all([f.name for f in p.fields] == ["Instance", "Val"] for p in plans)


def test_payload_size_and_values(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        meta, reg = scan_metadata(src)
        sample = next(m for m in src.iter_messages() if m.get_type() == "MINI")
    spec = reg.format_by_name("MINI")
    assert spec.type_id == MINI_TYPE
    ts = extract_timestamp_us(sample, spec)
    assert ts == 1_000_000
    plans, _ = build_topic_plans(meta, reg, _stats_for(reg, "MINI"))
    plan = next(p for p in plans if p.df_name == "MINI")
    payload = build_payload(plan, sample, 12345)
    assert len(payload) == plan.payload_size == plan.ulog_format.payload_size()
    assert len(payload) == 8 + sum(f.size_bytes for f in plan.ulog_format.fields[1:])
    decoded = _decode(plan, payload)
    assert decoded["timestamp"] == 12345
    expected = fx.manifest["MINI"]
    for name, want in expected.items():
        if name == "timestamp":
            continue
        if isinstance(want, float):
            assert decoded[name] == pytest.approx(want, abs=1e-6)
        else:
            assert decoded[name] == want
    timeus_field = [f for f in plan.fields if f.source_column == "TimeUS"]
    assert timeus_field == []  # timestamp column is not duplicated as data


def test_can_map_format_rules():
    reg = _registry_for()
    ok = DfFormatSpec(1, 15, "T", "Qf", ("TimeUS", "Val"))
    assert can_map_format(ok, reg) == (True, None)
    col_mismatch = DfFormatSpec(2, 15, "T2", "Qfff", ("TimeUS", "Val"))
    assert can_map_format(col_mismatch, reg)[0] is False
    unknown = DfFormatSpec(3, 15, "T3", "Qx", ("TimeUS", "Val"))
    assert can_map_format(unknown, reg)[0] is False
    nots = DfFormatSpec(4, 12, "T4", "Qf", ("Time", "Val"))
    assert can_map_format(nots, reg)[0] is False


def test_field_name_dedup_and_reserved():
    spec = DfFormatSpec(
        99, 3 + 8 + 4 + 1 + 1, "T", "QfBB", ("TimeUS", "A", "A", "timestamp")
    )
    reg = _registry_for(spec)
    plans, warnings = build_topic_plans(
        _meta_for(reg), reg, {(99, None): TopicStats(2, 100, 200)}
    )
    plan = plans[0]
    assert [f.name for f in plan.fields] == ["A", "A_2", "col_timestamp"]
    assert warnings  # field renames are reported


def test_time_ms_column_plan():
    spec = DfFormatSpec(5, 3 + 4 + 4, "TMS", "If", ("TimeMS", "Val"))
    reg = _registry_for(spec)
    plans, _ = build_topic_plans(
        _meta_for(reg), reg, {(5, None): TopicStats(1, 0, 0)}
    )
    plan = plans[0]
    assert plan.timestamp_column == "TimeMS"
    assert plan.timestamp_multiplier == 1000
    assert [f.name for f in plan.fields] == ["Val"]


def test_all_chars_types_and_sizes(tmp_path):
    fx = make_all_chars_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        meta, reg = scan_metadata(src)
        msgs = {}
        for m in src.iter_messages():
            msgs.setdefault(m.get_type(), m)
    plans, _ = build_topic_plans(
        meta,
        reg,
        {(ALLA_TYPE, None): TopicStats(1, 1000, 1000), (ALLB_TYPE, None): TopicStats(1, 1000, 1000)},
    )
    by_name = {p.df_name: p for p in plans}
    alla = by_name["ALLA"]
    types = {f.source_column: (f.ulog_type, f.array_len) for f in alla.fields}
    assert types["a"] == ("int16_t", 32)
    assert types["b"] == ("int8_t", 1)
    assert types["B"] == ("uint8_t", 1)
    assert types["h"] == ("int16_t", 1)
    assert types["H"] == ("uint16_t", 1)
    assert types["i"] == ("int32_t", 1)
    assert types["I"] == ("uint32_t", 1)
    assert types["q"] == ("int64_t", 1)
    assert types["f"] == ("float", 1)
    assert types["d"] == ("double", 1)
    assert types["g"] == ("float", 1)
    assert types["n"] == ("char", 4)
    assert types["N"] == ("char", 16)
    assert types["Z"] == ("char", 64)
    assert alla.payload_size == fx.manifest["ALLA_payload_size"]
    allb = by_name["ALLB"]
    types_b = {f.source_column: f.ulog_type for f in allb.fields}
    assert types_b == {
        "c": "float",
        "C": "float",
        "e": "float",
        "E": "float",
        "L": "double",
        "M": "uint8_t",
    }
    assert allb.payload_size == fx.manifest["ALLB_payload_size"]
    payload = build_payload(alla, msgs["ALLA"], 1000)
    decoded = _decode(alla, payload)
    assert decoded["a"] == fx.manifest["ALLA"]["a"]
    assert decoded["q"] == -5000000000
    assert decoded["I"] == 4000000000
    assert decoded["n"] == "ab"
    assert decoded["N"] == "hello"
    assert decoded["Z"] == "world"
    payload_b = build_payload(allb, msgs["ALLB"], 2000)
    decoded_b = _decode(allb, payload_b)
    assert decoded_b["L"] == pytest.approx(47.1234567, abs=1e-9)
    assert decoded_b["M"] == 200
    assert decoded_b["c"] == pytest.approx(1.23, abs=1e-6)


def test_normalize_value():
    array_field = FieldPlan("x", "int16_t", 32, "A", 1, "a", "")
    values = array.array("h", range(-16, 16))
    assert normalize_value(values, array_field) == struct.pack("<32h", *range(-16, 16))
    assert normalize_value("[1 -2 3]", array_field) == struct.pack(
        "<32h", 1, -2, 3, *([0] * 29)
    )
    assert normalize_value("[1] " , array_field) == struct.pack("<32h", 1, *([0] * 31))
    too_many = array.array("h", range(40))
    assert normalize_value(too_many, array_field) == struct.pack("<32h", *range(32))

    char_field = FieldPlan("tag", "char", 4, "tag", 2, "Z", "")
    assert normalize_value("abcdef", char_field) == b"abcd"
    assert normalize_value("ab", char_field) == b"ab\x00\x00"

    m_bin = FieldPlan("m", "uint8_t", 1, "M", 3, "M", "")
    assert normalize_value(-56, m_bin) == b"\xc8"
    assert normalize_value("7", m_bin) == b"\x07"

    b_field = FieldPlan("b", "int8_t", 1, "B", 1, "b", "")
    with pytest.raises(ValueError):
        normalize_value(1000, b_field)
    with pytest.raises(ValueError):
        normalize_value(None, b_field)


def test_build_payload_byte_exact(tmp_path):
    fx = make_minimal_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        meta, reg = scan_metadata(src)
        sample = next(m for m in src.iter_messages() if m.get_type() == "MINI")
    plans, _ = build_topic_plans(meta, reg, _stats_for(reg, "MINI"))
    plan = plans[0]
    payload = build_payload(plan, sample, 42)
    assert payload[:8] == struct.pack("<Q", 42)
    assert payload[8:12] == struct.pack("<f", 1.5)
    assert payload[12:13] == struct.pack("<B", 7)
    assert payload[13:17] == struct.pack("<i", 111)
    assert payload[17:] == b"abc" + b"\x00" * 61
    # missing attribute -> ValueError (caller converts to skip/field_error)
    with pytest.raises(ValueError):
        build_payload(plan, SimpleNamespace(X=1.0), 42)


def test_build_payload_fast_path_matches_slow_path(tmp_path):
    """The optimized single-struct packer must be byte-identical to the per-field path."""
    fx = make_all_chars_fixture(tmp_path)
    with DataFlashSource(fx.bin_path) as src:
        meta, reg = scan_metadata(src)
        messages = [
            m for m in src.iter_messages() if m.get_type() in ("ALLA", "ALLB")
        ]
    stats = {
        (ALLA_TYPE, None): TopicStats(1, 1000, 1000),
        (ALLB_TYPE, None): TopicStats(1, 2000, 2000),
    }
    plans, _ = build_topic_plans(meta, reg, stats)
    by_name = {p.df_name: p for p in plans}
    assert len(messages) == 2
    for msg in messages:
        plan = by_name[msg.get_type()]
        fast = build_payload(plan, msg, 777)
        slow = struct.pack("<Q", 777) + b"".join(
            normalize_value(getattr(msg, field.source_column), field)
            for field in plan.fields
        )
        assert fast == slow
