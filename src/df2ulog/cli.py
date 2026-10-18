"""Command line interface (plan §4.10, appendix C): convert / verify / inspect."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .converter import (
    ConversionOptions,
    build_conversion_plan,
    convert_file,
    scan_topic_stats,
)
from .df_source import DataFlashSource, scan_metadata
from .errors import (
    EXIT_CONVERT,
    EXIT_INPUT,
    EXIT_OK,
    EXIT_OUTPUT,
    EXIT_USAGE,
    EXIT_VERIFY,
    DataFlashReadError,
    Df2UlogError,
    InputFormatError,
    OutputExistsError,
    TimeOrderError,
    UnsupportedFormatCharError,
    VerificationError,
)
from .mapping import build_topic_plans
from .verifier import VerifyOptions, verify_ulog


def _add_verbosity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress summary")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="df2ulog",
        description="Convert ArduPilot DataFlash logs (.BIN/.log) to PX4 ULog (.ulg)",
    )
    parser.add_argument(
        "--version", action="version", version=f"df2ulog {__version__}"
    )
    sub = parser.add_subparsers(dest="command", metavar="{convert,verify,inspect}")

    convert = sub.add_parser("convert", help="convert a DataFlash log to ULog")
    convert.add_argument("source")
    convert.add_argument("-o", "--output", help="output .ulg path")
    convert.add_argument("--force", action="store_true", help="overwrite output")
    convert.add_argument(
        "--strict",
        action="store_true",
        help="fail on field conversion / missing timestamps / large tail",
    )
    convert.add_argument(
        "--allow-time-reset",
        action="store_true",
        help="correct >1 s backward timestamp jumps instead of failing",
    )
    convert.add_argument(
        "--params", choices=("initial", "none"), default="initial"
    )
    convert.add_argument(
        "--no-logging", action="store_true", help="do not write MSG/EV/MODE L records"
    )
    convert.add_argument("--report", help="write a text report")
    convert.add_argument("--report-json", help="write a JSON report")
    convert.add_argument(
        "--verify", action="store_true", help="verify the output right after conversion"
    )
    convert.add_argument(
        "--dry-run", action="store_true", help="scan and print a summary, write nothing"
    )
    _add_verbosity(convert)

    verify = sub.add_parser("verify", help="verify a .ulg file")
    verify.add_argument("ulg")
    verify.add_argument("--source", help="source DataFlash log for full replay")
    verify.add_argument("--report-json", help="conversion JSON report")
    _add_verbosity(verify)

    inspect = sub.add_parser("inspect", help="inspect a DataFlash log")
    inspect.add_argument("source")
    inspect.add_argument("--limit", type=int, default=0, help="only show first N topics")
    _add_verbosity(inspect)
    return parser


def _reconfigure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - exotic streams
            pass


def _fail(message: str, code: int) -> int:
    print(f"error: {message}", file=sys.stderr)
    return code


def _summary(result) -> str:
    lines = [
        (
            f"input : {result.source_path.name} "
            f"({result.source_format}, {result.source_size} B)"
        ),
        f"output: {result.output_path} ({result.output_size} B)",
        f"  sha256: {result.output_sha256}",
        (
            f"topics: {len(result.topics)} "
            f"({len({plan.df_type_id for plan in result.topics})} DF types), "
            f"data records: {result.data_record_count}"
        ),
        (
            f"params: {result.params_written}, "
            f"logging records: {result.logging_records}, "
            f"info records: {result.info_records}"
        ),
        f"elapsed: {result.elapsed_s:.3f} s",
    ]
    if result.source_tail_bytes:
        lines.append(f"source tail: {result.source_tail_bytes} B (see warnings)")
    return "\n".join(lines)


def _print_verify(result, prefix: str = "") -> None:
    verdict = "PASS" if result.ok else "FAIL"
    print(f"{prefix}{verdict}")
    for check in result.checks:
        status = "PASS" if check.ok else "FAIL"
        print(f"  [{status}] {check.name}: {check.detail}")
        for failure in check.failures[:5]:
            print(f"      - {failure}")


def _cmd_convert(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.is_file():
        raise InputFormatError(f"input file not found: {source}")
    options = ConversionOptions(
        output=Path(args.output) if args.output else None,
        force=args.force,
        strict=args.strict,
        allow_time_reset=args.allow_time_reset,
        params_mode=args.params,
        keep_logging=not args.no_logging,
        report_txt=Path(args.report) if args.report else None,
        report_json=Path(args.report_json) if args.report_json else None,
    )
    if args.dry_run:
        with DataFlashSource(source) as src:
            plan = build_conversion_plan(src, options)
        output = options.output or source.with_suffix(".ulg")
        if not args.quiet:
            total = sum(stat.count for stat in plan.stats.values())
            print(f"dry-run: {source.name} -> {output.name}")
            print(
                f"  format={plan.meta.source_format} "
                f"df_messages={plan.meta.df_message_count} topics={len(plan.plans)} "
                f"data_records={total} params={len(plan.meta.params)}"
            )
            print(f"  firmware={plan.meta.firmware!r}")
        return EXIT_OK

    result = convert_file(source, options)
    if not args.quiet:
        print(_summary(result))
    if args.verify:
        verification = verify_ulog(
            VerifyOptions(
                ulg_path=result.output_path,
                source_path=source,
                report_json=options.report_json,
                conversion_options=options,
            )
        )
        _print_verify(verification, prefix="verify: ")
        return EXIT_OK if verification.ok else EXIT_VERIFY
    return EXIT_OK


def _cmd_verify(args: argparse.Namespace) -> int:
    ulg_path = Path(args.ulg)
    if not ulg_path.is_file():
        raise VerificationError(f"ULog file not found: {ulg_path}")
    result = verify_ulog(
        VerifyOptions(
            ulg_path=ulg_path,
            source_path=Path(args.source) if args.source else None,
            report_json=Path(args.report_json) if args.report_json else None,
        )
    )
    if not args.quiet:
        _print_verify(result)
    return EXIT_OK if result.ok else EXIT_VERIFY


def _cmd_inspect(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.is_file():
        raise InputFormatError(f"input file not found: {source}")
    with DataFlashSource(source) as src:
        meta, registry = scan_metadata(src)
        stats, skipped, _warnings = scan_topic_stats(src, meta, registry)
    plans, _plan_warnings = build_topic_plans(meta, registry, stats)
    print(f"source   : {source}")
    print(f"format   : {meta.source_format}")
    print(f"messages : {meta.df_message_count}")
    print(f"FMT      : {len(meta.formats)} (DF message types)")
    print(f"params   : {len(meta.params)}")
    print(f"firmware : {meta.firmware!r}")
    print(f"board    : {meta.board!r}")
    print(f"frame    : {meta.frame!r}")
    print(f"gps utc  : {meta.gps_utc!r} (week={meta.gps_week}, ms={meta.gps_ms})")
    print(f"skipped  : {skipped}")
    print(f"topics   : {len(plans)}")
    limit = args.limit if args.limit and args.limit > 0 else len(plans)
    for plan in plans[:limit]:
        stat = stats[(plan.df_type_id, plan.instance)]
        instance = "-" if plan.instance is None else str(plan.instance)
        signature = ",".join(
            f"{field.name}:{field.ulog_type}"
            + (f"[{field.array_len}]" if field.array_len > 1 else "")
            for field in plan.fields
        )
        print(
            f"  {plan.df_name:6s} inst={instance:>4s} -> "
            f"{plan.ulog_name}.{plan.multi_id:02d} "
            f"count={stat.count} t=[{stat.first_ts_us},{stat.last_ts_us}] "
            f"fields={signature}"
        )
    if len(plans) > limit:
        print(f"  ... ({len(plans) - limit} more topics; use --limit to show them)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    _reconfigure_stdout()
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if (
        argv_list
        and not argv_list[0].startswith("-")
        and argv_list[0] not in ("convert", "verify", "inspect")
    ):
        argv_list.insert(0, "convert")
    parser = build_parser()
    try:
        args = parser.parse_args(argv_list)
    except SystemExit as exc:  # argparse: -h/--version/usage errors
        return exc.code if isinstance(exc.code, int) else EXIT_USAGE
    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_USAGE
    try:
        if args.command == "convert":
            return _cmd_convert(args)
        if args.command == "verify":
            return _cmd_verify(args)
        return _cmd_inspect(args)
    except InputFormatError as exc:
        return _fail(str(exc), EXIT_INPUT)
    except DataFlashReadError as exc:
        return _fail(str(exc), EXIT_INPUT)
    except OutputExistsError as exc:
        return _fail(str(exc), EXIT_OUTPUT)
    except VerificationError as exc:
        return _fail(str(exc), EXIT_VERIFY)
    except UnsupportedFormatCharError as exc:
        return _fail(str(exc), EXIT_CONVERT)
    except TimeOrderError as exc:
        return _fail(str(exc), EXIT_CONVERT)
    except Df2UlogError as exc:
        return _fail(str(exc), EXIT_CONVERT)
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        print("interrupted", file=sys.stderr)
        return 130
    except BrokenPipeError:  # pragma: no cover - pipe close
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 - last-resort CLI guard
        if getattr(args, "verbose", False):
            traceback.print_exc()
        return _fail(f"unexpected error: {exc}", EXIT_CONVERT)
