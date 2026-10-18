"""Text / JSON conversion reports (plan §4.8, appendix D)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import __version__
from .converter import ConversionResult
from .ulog_lint import LintReport

REPORT_SCHEMA_VERSION = 1


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_json_report(result: ConversionResult) -> dict:
    topic_rows = []
    for plan in result.topics:
        key = (plan.ulog_name, plan.multi_id)
        topic_rows.append(
            {
                "df_name": plan.df_name,
                "instance": plan.instance,
                "ulog_name": plan.ulog_name,
                "multi_id": plan.multi_id,
                "msg_id": result.msg_ids.get(key),
                "count": result.topic_counts.get(key, 0),
                "first_ts_us": result.topic_first_ts.get(key),
                "last_ts_us": result.topic_last_ts.get(key),
                "nudged": result.topic_nudged.get(key, 0),
                "payload_size": plan.payload_size,
                "fields": [
                    {
                        "name": field_plan.name,
                        "ulog_type": field_plan.ulog_type,
                        "array_len": field_plan.array_len,
                        "unit": field_plan.unit,
                        "df_char": field_plan.df_char,
                        "source_index": field_plan.source_index,
                    }
                    for field_plan in plan.fields
                ],
            }
        )
    topic_rows.sort(key=lambda row: (row["ulog_name"], row["multi_id"]))

    firsts = [ts for ts in result.topic_first_ts.values()]
    lasts = [ts for ts in result.topic_last_ts.values()]
    counts = {
        "df_messages": result.df_message_count,
        "data_records": result.data_record_count,
        "topics": len(result.topics),
        "df_message_types": len({plan.df_type_id for plan in result.topics}),
        "params": result.params_written,
        "logging_records": result.logging_records,
        "info_records": result.info_records,
        "meta_counts": dict(sorted(result.meta_counts.items())),
        "skipped": dict(sorted(result.skipped.items())),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool": {"name": "df2ulog", "version": __version__},
        "generated_at": _now_iso(),
        "source": {
            "path": str(result.source_path),
            "format": result.source_format,
            "size": result.source_size,
            "sha256": result.source_sha256,
        },
        "output": {
            "path": str(result.output_path),
            "size": result.output_size,
            "sha256": result.output_sha256,
        },
        "options": {
            "params_mode": result.options.params_mode,
            "keep_logging": result.options.keep_logging,
            "allow_time_reset": result.options.allow_time_reset,
            "strict": result.options.strict,
        },
        "counts": counts,
        "source_tail_bytes": result.source_tail_bytes,
        "time_range_us": {
            "first": min(firsts) if firsts else None,
            "last": max(lasts) if lasts else None,
        },
        "firmware": result.firmware,
        "board": result.board,
        "frame": result.frame,
        "gps_utc": result.gps_utc,
        "gps_week": result.gps_week,
        "gps_ms": result.gps_ms,
        "rtc_utc": result.rtc_utc,
        "topics": topic_rows,
        "warnings": list(result.warnings),
        "elapsed_s": round(result.elapsed_s, 3),
    }


def render_text_report(
    result: ConversionResult, lint: LintReport | None = None
) -> str:
    lines: list[str] = []
    lines.append(f"df2ulog {__version__} conversion report")
    lines.append("=" * 72)
    lines.append(
        f"source      : {result.source_path} "
        f"({result.source_format}, {result.source_size} B)"
    )
    lines.append(f"source sha256: {result.source_sha256}")
    lines.append(
        f"output      : {result.output_path} ({result.output_size} B)"
    )
    lines.append(f"output sha256: {result.output_sha256}")
    lines.append(f"elapsed     : {result.elapsed_s:.3f} s")
    df_types = len({plan.df_type_id for plan in result.topics})
    lines.append("")
    lines.append("counts")
    lines.append("-" * 72)
    lines.append(f"df messages        : {result.df_message_count}")
    lines.append(f"data records       : {result.data_record_count}")
    lines.append(f"topics             : {len(result.topics)} ({df_types} DF types)")
    lines.append(f"parameters written : {result.params_written}")
    lines.append(f"logging records    : {result.logging_records}")
    lines.append(f"info records       : {result.info_records}")
    lines.append(f"source tail bytes  : {result.source_tail_bytes}")
    firsts = list(result.topic_first_ts.values())
    lasts = list(result.topic_last_ts.values())
    if firsts and lasts:
        lines.append(f"time range (us)    : {min(firsts)} .. {max(lasts)}")
    total_nudged = sum(result.topic_nudged.values())
    lines.append(f"timestamp nudges   : {total_nudged}")
    lines.append(f"firmware           : {result.firmware!r}")
    lines.append(f"board              : {result.board!r}")
    lines.append(f"frame              : {result.frame!r}")
    lines.append(f"gps utc            : {result.gps_utc!r}")
    lines.append(f"rtc utc            : {result.rtc_utc!r}")
    if result.meta_counts:
        meta = ", ".join(
            f"{name}={count}" for name, count in sorted(result.meta_counts.items())
        )
        lines.append(f"meta messages      : {meta}")
    if result.skipped:
        lines.append(
            "skipped            : "
            + ", ".join(f"{k}={v}" for k, v in sorted(result.skipped.items()))
        )
    lines.append("")
    lines.append("topics (ulog_name.multi_id)")
    lines.append("-" * 72)
    lines.append(
        f"{'DF name':8s} {'inst':>4s} {'ulog name':20s} {'multi':>5s} "
        f"{'msg_id':>6s} {'count':>8s} {'first_us':>12s} {'last_us':>12s} "
        f"{'nudge':>5s} {'payload':>7s}"
    )
    for plan in result.topics:
        key = (plan.ulog_name, plan.multi_id)
        instance = "-" if plan.instance is None else str(plan.instance)
        lines.append(
            f"{plan.df_name:8s} {instance:>4s} {plan.ulog_name:20s} "
            f"{plan.multi_id:>5d} {result.msg_ids.get(key, -1):>6d} "
            f"{result.topic_counts.get(key, 0):>8d} "
            f"{result.topic_first_ts.get(key, 0):>12d} "
            f"{result.topic_last_ts.get(key, 0):>12d} "
            f"{result.topic_nudged.get(key, 0):>5d} {plan.payload_size:>7d}"
        )
    lines.append("")
    for plan in result.topics:
        signature = ",".join(
            f"{field_plan.name}:{field_plan.ulog_type}"
            + (f"[{field_plan.array_len}]" if field_plan.array_len > 1 else "")
            for field_plan in plan.fields
        )
        lines.append(
            f"  {plan.ulog_name}.{plan.multi_id:02d} "
            f"({plan.df_name}, payload {plan.payload_size} B): {signature}"
        )
    if lint is not None:
        lines.append("")
        lines.append("linter")
        lines.append("-" * 72)
        lines.append(
            f"ok={lint.ok} errors={len(lint.errors())} "
            f"warnings={len(lint.warnings())}"
        )
        for issue in lint.issues:
            lines.append(f"  [{issue.severity}] offset {issue.offset}: {issue.message}")
    if result.warnings:
        lines.append("")
        lines.append("warnings")
        lines.append("-" * 72)
        for warning in result.warnings:
            lines.append(f"  - {warning}")
    lines.append("")
    return "\n".join(lines)


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part_path = path.with_name(path.name + ".part")
    try:
        with open(part_path, "w", encoding="utf-8", newline="\n") as fp:
            fp.write(text)
        os.replace(part_path, path)
    finally:
        if part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass


def write_reports(result: ConversionResult, lint: LintReport | None = None) -> None:
    """Atomically write the requested text/JSON reports."""
    options = result.options
    if options.report_txt is not None:
        _atomic_write_text(Path(options.report_txt), render_text_report(result, lint))
    if options.report_json is not None:
        payload = json.dumps(
            build_json_report(result), ensure_ascii=False, indent=2
        )
        _atomic_write_text(Path(options.report_json), payload + "\n")
