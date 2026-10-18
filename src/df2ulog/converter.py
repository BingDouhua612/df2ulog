"""Conversion pipeline: pass A/B/C, streaming ULog output (plan §4.7, ADR-13)."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pymavlink import mavutil

from . import __version__
from .df_source import (
    DataFlashRegistry,
    DataFlashSource,
    DfFormatSpec,
    MetadataScan,
    SourceFormat,
    scan_metadata,
)
from .errors import (
    Df2UlogError,
    InputFormatError,
    OutputExistsError,
    TimeOrderError,
)
from .mapping import (
    TopicStats,
    UlogTopicPlan,
    build_payload,
    build_topic_plans,
    can_map_format,
)
from .ulog_writer import UlogWriter
from .unit_tables import event_name

_ONE_SECOND_US = 1_000_000
_TAIL_STRICT_BYTES = 528
_FIELD_ERROR_RE = re.compile(r"field '([^']+)'")

_META_TYPES = frozenset({"FMT", "FMTU", "UNIT", "MULT", "PARM", "VER", "RTC"})
_LOG_TYPES = frozenset({"MSG", "EV", "MODE"})
_OTHER_SKIP_TYPES = frozenset({"FILE", "DU32", "D32", "D16", "DFLT"})


@dataclass(frozen=True)
class ConversionOptions:
    output: Path | None = None
    force: bool = False
    strict: bool = False
    allow_time_reset: bool = False
    params_mode: Literal["initial", "none"] = "initial"
    keep_logging: bool = True
    report_txt: Path | None = None
    report_json: Path | None = None


@dataclass
class ConversionPlan:
    meta: MetadataScan
    registry: DataFlashRegistry
    stats: dict[tuple[int, int | None], TopicStats]
    plans: list[UlogTopicPlan]
    plans_by_key: dict[tuple[int, int | None], UlogTopicPlan]
    msg_ids: dict[tuple[str, int], int]
    start_ts_us: int
    skipped: dict[str, int]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ConversionResult:
    source_path: Path
    source_format: SourceFormat
    output_path: Path
    source_size: int
    output_size: int
    source_sha256: str
    output_sha256: str
    df_message_count: int
    data_record_count: int
    topics: list[UlogTopicPlan]
    msg_ids: dict[tuple[str, int], int]
    topic_counts: dict[tuple[str, int], int]
    topic_first_ts: dict[tuple[str, int], int]
    topic_last_ts: dict[tuple[str, int], int]
    topic_nudged: dict[tuple[str, int], int]
    params_written: int
    logging_records: int
    info_records: int
    meta_counts: dict[str, int]
    skipped: dict[str, int]
    warnings: list[str]
    gps_utc: str | None
    gps_week: int | None
    gps_ms: int | None
    rtc_utc: str | None
    firmware: str | None
    board: str | None
    frame: str | None
    source_tail_bytes: int
    elapsed_s: float
    options: ConversionOptions


@dataclass
class WriteCounters:
    data_records: int = 0
    logging_records: int = 0
    topic_counts: dict[tuple[str, int], int] = field(default_factory=dict)
    topic_first_ts: dict[tuple[str, int], int] = field(default_factory=dict)
    topic_last_ts: dict[tuple[str, int], int] = field(default_factory=dict)
    topic_nudged: dict[tuple[str, int], int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutputRecord:
    kind: Literal["data", "log"]
    timestamp_us: int
    ulog_name: str | None = None
    multi_id: int | None = None
    payload: bytes | None = None
    text: str | None = None


@dataclass(frozen=True)
class _TypeHandler:
    """Precomputed per-DF-type decision shared by pass B and pass C.

    Replaces the per-message classification chain with a single dict lookup keyed
    by ``msg.fmt.type`` (identical decisions, ~5x faster on 230k-message logs).
    """

    kind: Literal["skip", "data", "log"]
    type_id: int | None = None
    df_name: str = ""
    skip_key: str | None = None
    log_type: str | None = None
    timestamp_column: str | None = None
    timestamp_multiplier: int = 1
    instance_column: str | None = None


def _timestamp_column(spec: DfFormatSpec) -> tuple[str | None, int]:
    if "TimeUS" in spec.columns:
        return "TimeUS", 1
    if "TimeMS" in spec.columns:
        return "TimeMS", 1000
    return None, 1


def _build_handlers(
    registry: DataFlashRegistry,
    warnings: list[str],
    warn_once: set[Any],
) -> dict[int, _TypeHandler]:
    handlers: dict[int, _TypeHandler] = {}
    for type_id in sorted(registry.formats):
        spec = registry.formats[type_id]
        name = spec.name
        if name in _META_TYPES:
            handlers[type_id] = _TypeHandler("skip", df_name=name)
            continue
        if name in _OTHER_SKIP_TYPES:
            handlers[type_id] = _TypeHandler(
                "skip", df_name=name, skip_key=f"type:{name}"
            )
            continue
        timestamp_column, multiplier = _timestamp_column(spec)
        if name in _LOG_TYPES:
            if timestamp_column is None:
                handlers[type_id] = _TypeHandler(
                    "skip", df_name=name, skip_key="no_timestamp"
                )
            else:
                handlers[type_id] = _TypeHandler(
                    "log",
                    df_name=name,
                    log_type=name,
                    timestamp_column=timestamp_column,
                    timestamp_multiplier=multiplier,
                )
            continue
        ok, reason = can_map_format(spec, registry)
        if not ok:
            skip_key = f"unmappable:{reason}"
            if skip_key not in warn_once:
                warnings.append(f"DF type {name!r} skipped: {reason}")
                warn_once.add(skip_key)
            handlers[type_id] = _TypeHandler(
                "skip", df_name=name, skip_key=skip_key
            )
            continue
        assert timestamp_column is not None  # can_map_format guarantees it
        instance_index = registry.instance_column_index(type_id)
        handlers[type_id] = _TypeHandler(
            "data",
            type_id=type_id,
            df_name=name,
            timestamp_column=timestamp_column,
            timestamp_multiplier=multiplier,
            instance_column=(
                spec.columns[instance_index] if instance_index is not None else None
            ),
        )
    return handlers


def _effective_handler(
    msg: Any,
    handlers: dict[int, _TypeHandler],
    skipped: dict[str, int],
) -> _TypeHandler | None:
    """Fast path: one dict lookup; rare fallback for registry-less message types."""
    handler = handlers.get(msg.fmt.type)
    if handler is not None:
        return handler
    name = msg.get_type()
    if name in _META_TYPES:
        return _TypeHandler("skip", df_name=name)
    if name in _OTHER_SKIP_TYPES:
        skip_key = f"type:{name}"
        skipped[skip_key] = skipped.get(skip_key, 0) + 1
        return _TypeHandler("skip", df_name=name, skip_key=skip_key)
    if name in _LOG_TYPES:
        return _TypeHandler(
            "log",
            df_name=name,
            log_type=name,
            timestamp_column="TimeUS",
            timestamp_multiplier=1,
        )
    skipped["unknown_type"] = skipped.get("unknown_type", 0) + 1
    return _TypeHandler("skip", df_name=name, skip_key="unknown_type")


def _log_text(msg: Any, type_name: str, mav_type: int) -> str:
    if type_name == "MSG":
        return str(getattr(msg, "Message", "")).replace("\x00", "").strip()
    if type_name == "EV":
        event_id = int(getattr(msg, "Id", -1))
        return f"EV: {event_name(event_id)} (id={event_id})"
    mode = getattr(msg, "Mode", None)
    try:
        mode_num = int(getattr(msg, "ModeNum", -1))
    except (TypeError, ValueError):
        mode_num = -1
    if isinstance(mode, str):
        mode_name: str | None = mode
    else:
        mode_name = None
        mapping = mavutil.mode_mapping_bynumber(mav_type) if mav_type else None
        if mapping is not None and mode_num in mapping:
            mode_name = mapping[mode_num]
        elif mode_num >= 0:
            mode_name = str(mode_num)
        else:
            mode_name = str(mode)
    return f"MODE: {mode_name} (num={mode_num}, raw={mode})"


def scan_topic_stats(
    source: DataFlashSource,
    meta: MetadataScan,
    registry: DataFlashRegistry,
) -> tuple[dict[tuple[int, int | None], TopicStats], dict[str, int], list[str]]:
    """Pass B: discover (type, instance) keys, record counts and time ranges."""
    _ = meta  # signature is frozen (§4.7); the registry carries everything needed
    warnings: list[str] = []
    warn_once: set[Any] = set()
    handlers = _build_handlers(registry, warnings, warn_once)
    stats_mut: dict[tuple[int, int | None], list[int]] = {}
    skipped: dict[str, int] = {}
    for msg in source.iter_messages():
        handler = handlers.get(msg.fmt.type)
        if handler is None:
            handler = _effective_handler(msg, handlers, skipped)
        if handler.kind == "skip":
            if handler.skip_key is not None:
                skipped[handler.skip_key] = skipped.get(handler.skip_key, 0) + 1
            continue
        getter = msg.__getattr__
        try:
            timestamp_us = (
                int(getter(handler.timestamp_column)) * handler.timestamp_multiplier
            )
        except (TypeError, ValueError):
            skipped["no_timestamp"] = skipped.get("no_timestamp", 0) + 1
            continue
        if handler.kind == "log":
            continue
        instance: int | None = None
        if handler.instance_column is not None:
            try:
                instance = int(getter(handler.instance_column))
            except (TypeError, ValueError):
                instance = None
            if instance is None or not 0 <= instance <= 255:
                skipped["invalid_instance"] = skipped.get("invalid_instance", 0) + 1
                if "invalid_instance" not in warn_once:
                    warnings.append(
                        f"DF type {handler.df_name!r}: invalid/non-integer instance "
                        "value; those messages are skipped"
                    )
                    warn_once.add("invalid_instance")
                continue
        key = (handler.type_id, instance)
        entry = stats_mut.get(key)
        if entry is None:
            stats_mut[key] = [1, timestamp_us, timestamp_us]
        else:
            entry[0] += 1
            if timestamp_us < entry[1]:
                entry[1] = timestamp_us
            elif timestamp_us > entry[2]:
                entry[2] = timestamp_us
    stats = {
        key: TopicStats(count, first_ts, last_ts)
        for key, (count, first_ts, last_ts) in stats_mut.items()
    }
    return stats, skipped, warnings


def build_conversion_plan(
    source: DataFlashSource, options: ConversionOptions
) -> ConversionPlan:
    _ = options  # planning is option-independent today (§4.7 keeps the signature)
    meta, registry = scan_metadata(source)
    stats, skipped, warnings = scan_topic_stats(source, meta, registry)
    plans, plan_warnings = build_topic_plans(meta, registry, stats)
    warnings.extend(plan_warnings)
    if not plans:
        raise Df2UlogError(
            "no data topics selected: 没有可转换的数据 topic "
            "(unknown formats or missing timestamps?)"
        )
    plans_by_key = {(p.df_type_id, p.instance): p for p in plans}
    msg_ids = {(p.ulog_name, p.multi_id): index for index, p in enumerate(plans)}
    start_ts_us = min(
        stats[(p.df_type_id, p.instance)].first_ts_us for p in plans
    )
    return ConversionPlan(
        meta=meta,
        registry=registry,
        stats=stats,
        plans=plans,
        plans_by_key=plans_by_key,
        msg_ids=msg_ids,
        start_ts_us=start_ts_us,
        skipped=skipped,
        warnings=warnings,
    )


def iter_output_records(
    source: DataFlashSource,
    plan: ConversionPlan,
    options: ConversionOptions,
    counters: WriteCounters,
) -> Iterator[OutputRecord]:
    """Pass C: yield data/log records in source order, applying time/value rules."""
    handlers = _build_handlers(plan.registry, [], set())
    last_ts: dict[tuple[str, int], int] = {}
    warn_once: set[Any] = set()
    for msg in source.iter_messages():
        handler = handlers.get(msg.fmt.type)
        if handler is None:
            handler = _effective_handler(msg, handlers, {})
        if handler.kind == "skip":
            continue
        getter = msg.__getattr__
        try:
            timestamp_us = (
                int(getter(handler.timestamp_column)) * handler.timestamp_multiplier
            )
        except (TypeError, ValueError):
            continue
        if handler.kind == "log":
            if not options.keep_logging:
                continue
            counters.logging_records += 1
            yield OutputRecord(
                kind="log",
                timestamp_us=timestamp_us,
                text=_log_text(msg, handler.log_type, source.mav_type),
            )
            continue
        instance: int | None = None
        if handler.instance_column is not None:
            try:
                instance = int(getter(handler.instance_column))
            except (TypeError, ValueError):
                instance = None
            if instance is None or not 0 <= instance <= 255:
                continue
        topic = plan.plans_by_key.get((handler.type_id, instance))
        if topic is None:
            continue
        key = (topic.ulog_name, topic.multi_id)
        previous = last_ts.get(key)
        if previous is not None and timestamp_us <= previous:
            delta = previous - timestamp_us
            message = (
                f"timestamp went backwards by {delta} us for "
                f"{topic.ulog_name}.{topic.multi_id:02d}"
            )
            if delta > _ONE_SECOND_US:
                if not options.allow_time_reset:
                    raise TimeOrderError(
                        message,
                        ulog_name=topic.ulog_name,
                        multi_id=topic.multi_id,
                        previous_us=previous,
                        current_us=timestamp_us,
                    )
                if ("time_reset", key) not in warn_once:
                    counters.warnings.append(
                        f"HIGH: {message}; corrected with +1 us "
                        "(--allow-time-reset)"
                    )
                    warn_once.add(("time_reset", key))
            timestamp_us = previous + 1
            counters.topic_nudged[key] = counters.topic_nudged.get(key, 0) + 1
        last_ts[key] = timestamp_us
        try:
            payload = build_payload(topic, msg, timestamp_us)
        except ValueError as exc:
            match = _FIELD_ERROR_RE.search(str(exc))
            field_name = match.group(1) if match else "unknown"
            skip_key = f"field_error:{field_name}"
            counters.skipped[skip_key] = counters.skipped.get(skip_key, 0) + 1
            if skip_key not in warn_once:
                counters.warnings.append(f"field conversion failed: {exc}")
                warn_once.add(skip_key)
            if options.strict:
                raise Df2UlogError(
                    f"field conversion failed (--strict): {exc}"
                ) from exc
            continue
        counters.data_records += 1
        counters.topic_counts[key] = counters.topic_counts.get(key, 0) + 1
        counters.topic_first_ts.setdefault(key, timestamp_us)
        counters.topic_last_ts[key] = timestamp_us
        yield OutputRecord(
            kind="data",
            timestamp_us=timestamp_us,
            ulog_name=topic.ulog_name,
            multi_id=topic.multi_id,
            payload=payload,
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_info_records(plan: ConversionPlan, source_path: Path) -> dict[str, str]:
    meta = plan.meta
    infos: dict[str, str] = {
        "converter": f"df2ulog {__version__}",
        "source_file": source_path.name,
        "source_format": meta.source_format,
        "sys_name": "ArduPilot",
        "time_base": "microseconds since boot; no UTC shift",
    }
    if meta.firmware:
        infos["ver_sw"] = meta.firmware
    if meta.board:
        infos["ver_hw"] = meta.board
    if meta.frame:
        infos["frame"] = meta.frame
    if meta.gps_week is not None:
        infos["gps_week"] = str(meta.gps_week)
    if meta.gps_ms is not None:
        infos["gps_ms"] = str(meta.gps_ms)
    if meta.gps_utc:
        infos["gps_utc"] = meta.gps_utc
    if meta.rtc_utc:
        infos["rtc_utc"] = meta.rtc_utc
    return infos


def _merge_skipped(
    plan_skipped: dict[str, int], counter_skipped: dict[str, int]
) -> dict[str, int]:
    merged = dict(plan_skipped)
    for key, value in counter_skipped.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def convert_file(
    source_path: Path,
    options: ConversionOptions,
    *,
    progress_callback=None,
) -> ConversionResult:
    """Convert one DataFlash log to ULog.

    ``progress_callback(phase, percent)`` is an optional keyword-only extension
    for GUIs (docs/DECISIONS.md D-04); existing callers are unaffected.
    """
    started = time.perf_counter()

    def report(phase: str, percent: int) -> None:
        if progress_callback is not None:
            progress_callback(phase, max(0, min(100, int(percent))))

    report("scan", 0)
    source_path = Path(source_path)
    if not source_path.is_file():
        raise InputFormatError(f"input file not found: {source_path}")
    output_path = (
        Path(options.output)
        if options.output is not None
        else source_path.with_suffix(".ulg")
    )
    if output_path.resolve() == source_path.resolve():
        raise Df2UlogError("output path must differ from the input path")
    if output_path.exists() and not options.force:
        raise OutputExistsError(
            f"output already exists: {output_path} (use --force to overwrite)"
        )
    source_size = source_path.stat().st_size
    source_sha256 = _sha256_file(source_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    counters = WriteCounters()
    warnings: list[str] = []
    params_written = 0
    info_records = 0
    source_tail_bytes = 0
    plan: ConversionPlan | None = None
    try:
        with DataFlashSource(source_path) as source:
            plan = build_conversion_plan(source, options)
            report("planned", 20)
            total_records = max(
                1, sum(plan.stats[key].count for key in plan.plans_by_key)
            )
            last_progress = 25
            warnings.extend(plan.meta.warnings)
            warnings.extend(plan.warnings)
            infos = _build_info_records(plan, source_path)
            info_records = len(infos)
            with open(part_path, "wb") as fp:
                writer = UlogWriter(fp, plan.start_ts_us)
                writer.write_flag_bits()
                for key in sorted(infos):
                    writer.write_info(key, infos[key])
                written_formats: set[str] = set()
                for topic in plan.plans:
                    if topic.ulog_name in written_formats:
                        continue
                    writer.write_format(topic.ulog_format)
                    written_formats.add(topic.ulog_name)
                if options.params_mode == "initial":
                    for param_name in sorted(plan.meta.params):
                        value = plan.meta.params[param_name]
                        if not math.isfinite(value):
                            warnings.append(
                                f"parameter {param_name!r} not written: "
                                f"non-finite value {value!r}"
                            )
                            continue
                        writer.write_initial_parameter(param_name, value)
                        params_written += 1
                for topic in plan.plans:
                    writer.write_add_logged(
                        plan.msg_ids[(topic.ulog_name, topic.multi_id)],
                        topic.ulog_name,
                        topic.multi_id,
                    )
                report("definitions", 25)
                for written, record in enumerate(
                    iter_output_records(source, plan, options, counters), start=1
                ):
                    if record.kind == "data":
                        assert record.payload is not None
                        key = (record.ulog_name, record.multi_id)
                        writer.write_data(plan.msg_ids[key], record.payload)
                    else:
                        assert record.text is not None
                        writer.write_logging(record.timestamp_us, record.text, "6")
                    progress = 25 + int(70 * written / total_records)
                    if progress != last_progress:
                        last_progress = progress
                        report("write", min(95, progress))
                writer.write_sync()
                writer.flush()
            source_tail_bytes = source.unparsed_tail_bytes
        warnings.extend(counters.warnings)
        if source_tail_bytes > 0:
            warnings.append(
                f"source_tail_bytes={source_tail_bytes}: unparsed bytes at the end "
                "of the source log"
            )
        if options.strict and source_tail_bytes > _TAIL_STRICT_BYTES:
            raise Df2UlogError(
                f"source tail {source_tail_bytes} B exceeds {_TAIL_STRICT_BYTES} B "
                "(--strict)"
            )
        for param_name, values in plan.meta.param_conflicts.items():
            warnings.append(
                f"parameter {param_name!r} changed during the log: {values!r}"
            )
        total_nudged = sum(counters.topic_nudged.values())
        if total_nudged:
            warnings.append(
                f"timestamp nudges: {total_nudged} record(s) adjusted by +1 us"
            )
        os.replace(part_path, output_path)
    finally:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass
    report("done", 100)
    assert plan is not None
    output_size = output_path.stat().st_size
    output_sha256 = _sha256_file(output_path)
    result = ConversionResult(
        source_path=source_path,
        source_format=plan.meta.source_format,
        output_path=output_path,
        source_size=source_size,
        output_size=output_size,
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        df_message_count=plan.meta.df_message_count,
        data_record_count=counters.data_records,
        topics=plan.plans,
        msg_ids=plan.msg_ids,
        topic_counts=counters.topic_counts,
        topic_first_ts=counters.topic_first_ts,
        topic_last_ts=counters.topic_last_ts,
        topic_nudged=counters.topic_nudged,
        params_written=params_written,
        logging_records=counters.logging_records,
        info_records=info_records,
        meta_counts=plan.meta.meta_counts,
        skipped=_merge_skipped(plan.skipped, counters.skipped),
        warnings=warnings,
        gps_utc=plan.meta.gps_utc,
        gps_week=plan.meta.gps_week,
        gps_ms=plan.meta.gps_ms,
        rtc_utc=plan.meta.rtc_utc,
        firmware=plan.meta.firmware,
        board=plan.meta.board,
        frame=plan.meta.frame,
        source_tail_bytes=source_tail_bytes,
        elapsed_s=time.perf_counter() - started,
        options=options,
    )
    if options.report_txt is not None or options.report_json is not None:
        from .reports import write_reports

        write_reports(result)
    return result
