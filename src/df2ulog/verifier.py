"""Verifier (plan §4.9, ADR-15): lint + pyulog + exact source-replay comparison."""

from __future__ import annotations

import json
import math
import struct
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .converter import (
    ConversionOptions,
    WriteCounters,
    build_conversion_plan,
    iter_output_records,
)
from .df_source import DataFlashSource
from .errors import VerificationError
from .ulog_codec import SCALAR_STRUCT
from .ulog_lint import LintReport, lint_ulog

_REQUIRED_INFO_KEYS = ("sys_name", "source_file", "converter", "time_base")
_MAX_FAILURES = 20


@dataclass(frozen=True)
class VerifyOptions:
    ulg_path: Path
    source_path: Path | None = None
    report_json: Path | None = None
    conversion_options: ConversionOptions | None = None


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    failures: list[str]


@dataclass
class VerifyResult:
    ok: bool
    checks: list[CheckResult]
    lint: LintReport

    def failures(self) -> list[str]:
        out: list[str] = []
        for check in self.checks:
            out.extend(check.failures)
        return out


def _load_pyulog():
    try:
        import numpy
        import pyulog
    except ImportError as exc:  # pragma: no cover - exercised only without pyulog
        raise VerificationError("pyulog 未安装：pip install pyulog") from exc
    return pyulog, numpy


def _add_failure(failures: list[str], message: str) -> None:
    if len(failures) < _MAX_FAILURES:
        failures.append(message)


def _lint_check(lint: LintReport) -> CheckResult:
    failures = [f"lint error @{issue.offset}: {issue.message}" for issue in lint.errors()]
    return CheckResult(
        name="1-structure-lint",
        ok=lint.ok and not lint.errors(),
        detail=(
            f"ok={lint.ok} errors={len(lint.errors())} "
            f"warnings={len(lint.warnings())}"
        ),
        failures=failures[:_MAX_FAILURES],
    )


def _readback_check(pyulog, ulg_path: Path):
    failures: list[str] = []
    try:
        ulog = pyulog.ULog(str(ulg_path))
    except Exception as exc:  # noqa: BLE001 - any pyulog failure is a check failure
        return None, CheckResult(
            name="2-pyulog-readback",
            ok=False,
            detail=f"pyulog failed to read file: {exc}",
            failures=[f"pyulog exception: {exc}"],
        )
    if ulog.file_corruption:
        failures.append("pyulog reports file_corruption=True")
    if len(ulog.data_list) == 0:
        failures.append("pyulog data_list is empty (no data topics)")
    return ulog, CheckResult(
        name="2-pyulog-readback",
        ok=not failures,
        detail=(
            f"corruption={ulog.file_corruption} topics={len(ulog.data_list)} "
            f"data_records={sum(len(d.data.get('timestamp', [])) for d in ulog.data_list)}"
        ),
        failures=failures,
    )


def _field_width(field_plan: Any) -> int:
    if field_plan.ulog_type == "char":
        return field_plan.array_len
    return struct.calcsize("<" + SCALAR_STRUCT[field_plan.ulog_type]) * field_plan.array_len


def _decode_payload(topic: Any, payload: bytes) -> dict[str, Any]:
    """Independently decode a D payload using the frozen ULog format plan."""
    decoded: dict[str, Any] = {"timestamp": struct.unpack_from("<Q", payload, 0)[0]}
    offset = 8
    for field_plan in topic.fields:
        struct_char = SCALAR_STRUCT.get(field_plan.ulog_type, "b")
        if field_plan.ulog_type == "char":
            values = struct.unpack_from(
                "<" + "b" * field_plan.array_len, payload, offset
            )
            decoded[field_plan.name] = list(values)
        elif field_plan.array_len == 1:
            decoded[field_plan.name] = struct.unpack_from(
                "<" + struct_char, payload, offset
            )[0]
        else:
            decoded[field_plan.name] = list(
                struct.unpack_from(
                    "<" + struct_char * field_plan.array_len, payload, offset
                )
            )
        offset += _field_width(field_plan)
    return decoded


def _aggregate(
    bucket: dict[str, list],
    topic: Any,
    decoded: dict[str, Any],
) -> None:
    bucket.setdefault("timestamp", []).append(decoded["timestamp"])
    for field_plan in topic.fields:
        if field_plan.ulog_type == "char" or field_plan.array_len > 1:
            for index, value in enumerate(decoded[field_plan.name]):
                bucket.setdefault(f"{field_plan.name}[{index}]", []).append(value)
        else:
            bucket.setdefault(field_plan.name, []).append(decoded[field_plan.name])


def _collect_expected(source_path: Path, conv_options: ConversionOptions):
    expected_data: dict[tuple[str, int], dict[str, list]] = {}
    expected_logs: list[tuple[int, int, str]] = []
    params: dict[str, float] = {}
    with DataFlashSource(source_path) as source:
        plan = build_conversion_plan(source, conv_options)
        counters = WriteCounters()
        plans_by_key = {(p.ulog_name, p.multi_id): p for p in plan.plans}
        for record in iter_output_records(source, plan, conv_options, counters):
            if record.kind == "data":
                key = (record.ulog_name, record.multi_id)
                topic = plans_by_key[key]
                decoded = _decode_payload(topic, record.payload)
                _aggregate(expected_data.setdefault(key, {}), topic, decoded)
            else:
                expected_logs.append(
                    (ord("6"), record.timestamp_us, record.text or "")
                )
        if conv_options.params_mode == "initial":
            for name in sorted(plan.meta.params):
                value = plan.meta.params[name]
                if math.isfinite(value):
                    params[name] = value
    return plan, expected_data, expected_logs, params


def _compare_series(
    failures: list[str],
    label: str,
    expected: list,
    actual,
    ulog_type: str,
    np,
) -> None:
    if actual is None:
        _add_failure(failures, f"{label}: field missing from pyulog data")
        return
    actual_list = [value for value in actual]
    if len(actual_list) != len(expected):
        _add_failure(
            failures,
            f"{label}: record count {len(actual_list)} != expected {len(expected)}",
        )
        return
    if ulog_type == "float":
        left = np.asarray(expected, dtype=np.float32)
        right = np.asarray(actual_list, dtype=np.float32)
        equal = np.array_equal(left, right, equal_nan=True)
        bad = (
            np.where(~((left == right) | (np.isnan(left) & np.isnan(right))))[0]
            if not equal
            else []
        )
    elif ulog_type == "double":
        left = np.asarray(expected, dtype=np.float64)
        right = np.asarray(actual_list, dtype=np.float64)
        equal = np.array_equal(left, right, equal_nan=True)
        bad = (
            np.where(~((left == right) | (np.isnan(left) & np.isnan(right))))[0]
            if not equal
            else []
        )
    else:
        left = np.asarray(expected, dtype=np.int64)
        right = np.asarray(actual_list, dtype=np.int64)
        equal = np.array_equal(left, right)
        bad = np.where(left != right)[0] if not equal else []
    if not equal:
        index = int(bad[0]) if len(bad) else 0
        _add_failure(
            failures,
            f"{label}: mismatch at index {index}: "
            f"expected {expected[index]!r} actual {actual_list[index]!r}",
        )


def _compare_topics(
    failures: list[str],
    plan: Any,
    expected_data: dict[tuple[str, int], dict[str, list]],
    ulog: Any,
    np,
) -> None:
    actual = {(data.name, data.multi_id): data for data in ulog.data_list}
    topics_by_key = {(p.ulog_name, p.multi_id): p for p in plan.plans}
    for key in sorted(set(expected_data) - set(actual)):
        _add_failure(failures, f"topic {key} missing from .ulg")
    for key in sorted(set(actual) - set(expected_data)):
        _add_failure(failures, f"unexpected topic {key} in .ulg")
    for key in sorted(set(expected_data) & set(actual)):
        data = actual[key]
        topic = topics_by_key[key]
        expected_bucket = expected_data[key]
        expected_ts = expected_bucket.get("timestamp", [])
        actual_ts = [int(value) for value in data.data.get("timestamp", [])]
        if expected_ts != actual_ts:
            _add_failure(
                failures,
                f"topic {key}: timestamp mismatch "
                f"(expected {len(expected_ts)} records, got {len(actual_ts)})",
            )
        for field_plan in topic.fields:
            if field_plan.ulog_type == "char" or field_plan.array_len > 1:
                for index in range(field_plan.array_len):
                    label = f"{key}.{field_plan.name}[{index}]"
                    _compare_series(
                        failures,
                        label,
                        expected_bucket.get(f"{field_plan.name}[{index}]", []),
                        data.data.get(f"{field_plan.name}[{index}]"),
                        field_plan.ulog_type,
                        np,
                    )
            else:
                _compare_series(
                    failures,
                    f"{key}.{field_plan.name}",
                    expected_bucket.get(field_plan.name, []),
                    data.data.get(field_plan.name),
                    field_plan.ulog_type,
                    np,
                )


def _compare_params(
    failures: list[str],
    expected_params: dict[str, float],
    ulog: Any,
    np,
) -> None:
    actual = {name: float(value) for name, value in ulog.initial_parameters.items()}
    missing = sorted(set(expected_params) - set(actual))
    extra = sorted(set(actual) - set(expected_params))
    for name in missing[:5]:
        _add_failure(failures, f"parameter {name!r} missing from .ulg")
    for name in extra[:5]:
        _add_failure(failures, f"unexpected parameter {name!r} in .ulg")
    for name in sorted(set(expected_params) & set(actual)):
        left = np.float32(expected_params[name])
        right = np.float32(actual[name])
        if not (left == right or (np.isnan(left) and np.isnan(right))):
            _add_failure(
                failures,
                f"parameter {name!r}: expected {expected_params[name]!r} "
                f"actual {actual[name]!r}",
            )


def _compare_logs(
    failures: list[str],
    expected_logs: list[tuple[int, int, str]],
    ulog: Any,
) -> None:
    actual: list[tuple[int, int, str]] = []
    for message in ulog.logged_messages:
        actual.append(
            (
                int(message.log_level),
                int(message.timestamp),
                str(message.message),
            )
        )
    if Counter(expected_logs) == Counter(actual):
        return
    expected_counter = Counter(expected_logs)
    actual_counter = Counter(actual)
    for entry in list(expected_counter - actual_counter)[:10]:
        _add_failure(failures, f"L record missing: {entry!r}")
    for entry in list(actual_counter - expected_counter)[:10]:
        _add_failure(failures, f"unexpected L record: {entry!r}")


def _compare_info(failures: list[str], plan: Any, ulog: Any, source_path: Path) -> None:
    info = ulog.msg_info_dict
    for key in _REQUIRED_INFO_KEYS:
        if key not in info:
            _add_failure(failures, f"INFO record missing required key {key!r}")
    if plan.meta.firmware and "ver_sw" not in info:
        _add_failure(failures, "INFO record missing 'ver_sw' (firmware unknown)")
    source_file = info.get("source_file")
    if source_file is not None and source_file != source_path.name:
        _add_failure(
            failures,
            f"INFO source_file {source_file!r} != {source_path.name!r}",
        )


def _source_replay_check(
    source_path: Path,
    ulog: Any,
    conv_options: ConversionOptions,
    np,
) -> CheckResult:
    failures: list[str] = []
    try:
        plan, expected_data, expected_logs, expected_params = _collect_expected(
            source_path, conv_options
        )
    except Exception as exc:  # noqa: BLE001 - replay failure is a check failure
        return CheckResult(
            name="3-source-replay",
            ok=False,
            detail=f"source replay failed: {exc}",
            failures=[f"source replay failed: {exc}"],
        )
    _compare_topics(failures, plan, expected_data, ulog, np)
    if conv_options.params_mode == "initial":
        _compare_params(failures, expected_params, ulog, np)
    elif ulog.initial_parameters:
        _add_failure(
            failures, "params_mode=none but .ulg contains initial parameters"
        )
    if conv_options.keep_logging:
        _compare_logs(failures, expected_logs, ulog)
    elif ulog.logged_messages:
        _add_failure(failures, "keep_logging=False but .ulg contains L records")
    _compare_info(failures, plan, ulog, source_path)
    total_expected = sum(len(bucket.get("timestamp", [])) for bucket in expected_data.values())
    return CheckResult(
        name="3-source-replay",
        ok=not failures,
        detail=(
            f"replayed {total_expected} data records across "
            f"{len(expected_data)} topics; failures={len(failures)}"
        ),
        failures=failures[:_MAX_FAILURES],
    )


def _report_json_check(report_path: Path, ulog: Any) -> CheckResult:
    failures: list[str] = []
    try:
        report = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return CheckResult(
            name="4-report-json",
            ok=False,
            detail=f"cannot read report json: {exc}",
            failures=[f"cannot read report json: {exc}"],
        )
    rows = {
        (row.get("ulog_name"), row.get("multi_id")): row
        for row in report.get("topics", [])
    }
    actual = {(data.name, data.multi_id): data for data in ulog.data_list}
    for key in sorted(set(rows) - set(actual)):
        _add_failure(failures, f"report topic {key} missing from .ulg")
    for key in sorted(set(actual) - set(rows)):
        _add_failure(failures, f"unexpected topic {key} not in report")
    for key in sorted(set(actual) & set(rows)):
        row = rows[key]
        timestamps = [int(value) for value in actual[key].data.get("timestamp", [])]
        if row.get("count") is not None and row["count"] != len(timestamps):
            _add_failure(
                failures,
                f"report topic {key}: count {row['count']} != {len(timestamps)}",
            )
        if timestamps:
            if row.get("first_ts_us") is not None and row["first_ts_us"] != timestamps[0]:
                _add_failure(failures, f"report topic {key}: first_ts_us mismatch")
            if row.get("last_ts_us") is not None and row["last_ts_us"] != timestamps[-1]:
                _add_failure(failures, f"report topic {key}: last_ts_us mismatch")
    counts = report.get("counts", {})
    if counts.get("data_records") is not None:
        actual_records = sum(
            len(data.data.get("timestamp", [])) for data in ulog.data_list
        )
        if counts["data_records"] != actual_records:
            _add_failure(
                failures,
                f"report data_records {counts['data_records']} != {actual_records}",
            )
    if counts.get("params") is not None and counts["params"] != len(
        ulog.initial_parameters
    ):
        _add_failure(failures, "report params count mismatch")
    if counts.get("logging_records") is not None and counts[
        "logging_records"
    ] != len(ulog.logged_messages):
        _add_failure(failures, "report logging_records count mismatch")
    return CheckResult(
        name="4-report-json",
        ok=not failures,
        detail=(
            f"compared {len(rows)} report topics against {len(actual)} .ulg topics; "
            f"failures={len(failures)}"
        ),
        failures=failures[:_MAX_FAILURES],
    )


def _resolve_conversion_options(options: VerifyOptions) -> ConversionOptions:
    if options.conversion_options is not None:
        return options.conversion_options
    if options.report_json is not None:
        report_path = Path(options.report_json)
        if report_path.is_file():
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                report = None
            if report is not None:
                stored = report.get("options", {})
                return ConversionOptions(
                    params_mode=stored.get("params_mode", "initial"),
                    keep_logging=bool(stored.get("keep_logging", True)),
                    allow_time_reset=bool(stored.get("allow_time_reset", False)),
                    strict=bool(stored.get("strict", False)),
                )
    return ConversionOptions()


def verify_ulog(options: VerifyOptions) -> VerifyResult:
    """Lint + pyulog readback + optional full source replay / report comparison."""
    ulg_path = Path(options.ulg_path)
    lint = lint_ulog(ulg_path)
    checks = [_lint_check(lint)]
    pyulog, np = _load_pyulog()
    ulog, readback = _readback_check(pyulog, ulg_path)
    checks.append(readback)
    if ulog is not None:
        conv_options = _resolve_conversion_options(options)
        if options.source_path is not None:
            checks.append(
                _source_replay_check(
                    Path(options.source_path), ulog, conv_options, np
                )
            )
        elif options.report_json is not None:
            checks.append(_report_json_check(Path(options.report_json), ulog))
    return VerifyResult(
        ok=all(check.ok for check in checks),
        checks=checks,
        lint=lint,
    )
