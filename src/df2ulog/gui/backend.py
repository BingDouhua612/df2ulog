"""Qt-free GUI back-end: request/outcome dataclasses, path policy, sync conversion."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..converter import ConversionOptions, ConversionResult, convert_file
from ..df_source import DataFlashSource, detect_format, scan_metadata
from ..errors import (
    EXIT_CONVERT,
    EXIT_INPUT,
    EXIT_OUTPUT,
    EXIT_VERIFY,
    DataFlashReadError,
    Df2UlogError,
    InputFormatError,
    OutputExistsError,
    TimeOrderError,
    UnsupportedFormatCharError,
)
from ..verifier import VerifyOptions, verify_ulog

ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class SourceInfo:
    path: Path
    size: int
    source_format: str


@dataclass(frozen=True)
class ConversionRequest:
    source: Path
    output_dir: Path | None = None
    output_name: str | None = None
    overwrite: bool = False
    verify: bool = False
    report_json: bool = False
    report_txt: bool = False
    params_mode: str = "initial"
    keep_logging: bool = True
    strict: bool = False
    allow_time_reset: bool = False


@dataclass(frozen=True)
class ConversionOutcome:
    ok: bool
    message: str
    error_code: int = 0
    output_path: Path | None = None
    result: ConversionResult | None = None
    report_json_path: Path | None = None
    report_txt_path: Path | None = None
    verify_ok: bool | None = None
    verify_failures: tuple[str, ...] = ()


def describe_source(path: Path) -> SourceInfo:
    path = Path(path)
    if not path.is_file():
        raise InputFormatError(f"文件不存在或不是普通文件：{path}")
    return SourceInfo(
        path=path, size=path.stat().st_size, source_format=detect_format(path)
    )


def output_path_for(request: ConversionRequest) -> Path:
    name = request.output_name or f"{request.source.stem}.ulg"
    if not name.lower().endswith(".ulg"):
        name += ".ulg"
    directory = (
        Path(request.output_dir)
        if request.output_dir is not None
        else request.source.parent
    )
    return directory / name


def _report_path(base: Path, suffix: str) -> Path:
    return base.with_name(f"{base.stem}{suffix}")


def run_conversion(
    request: ConversionRequest, progress: ProgressCallback | None = None
) -> ConversionOutcome:
    """Convert synchronously; never raises — errors become ConversionOutcome."""
    try:
        output_path = output_path_for(request)
        if output_path.exists() and not request.overwrite:
            return ConversionOutcome(
                ok=False,
                message=f"输出文件已存在：{output_path}（勾选“覆盖已存在文件”后重试）",
                error_code=EXIT_OUTPUT,
            )
        report_txt = (
            _report_path(output_path, "_report.txt") if request.report_txt else None
        )
        report_json = (
            _report_path(output_path, "_report.json") if request.report_json else None
        )
        options = ConversionOptions(
            output=output_path,
            force=request.overwrite,
            strict=request.strict,
            allow_time_reset=request.allow_time_reset,
            params_mode=request.params_mode,  # type: ignore[arg-type]
            keep_logging=request.keep_logging,
            report_txt=report_txt,
            report_json=report_json,
        )
        result = convert_file(request.source, options, progress_callback=progress)
        verify_ok: bool | None = None
        failures: tuple[str, ...] = ()
        if request.verify:
            verification = verify_ulog(
                VerifyOptions(
                    ulg_path=output_path,
                    source_path=request.source,
                    report_json=report_json,
                    conversion_options=options,
                )
            )
            verify_ok = bool(verification.ok)
            failures = tuple(verification.failures()[:5])
            if not verification.ok:
                return ConversionOutcome(
                    ok=False,
                    message="转换成功，但 verify 失败（详见校验结果）",
                    error_code=EXIT_VERIFY,
                    output_path=output_path,
                    result=result,
                    report_json_path=report_json,
                    report_txt_path=report_txt,
                    verify_ok=verify_ok,
                    verify_failures=failures,
                )
        return ConversionOutcome(
            ok=True,
            message="转换完成",
            output_path=output_path,
            result=result,
            report_json_path=report_json,
            report_txt_path=report_txt,
            verify_ok=verify_ok,
            verify_failures=failures,
        )
    except OutputExistsError as exc:
        return ConversionOutcome(ok=False, message=str(exc), error_code=EXIT_OUTPUT)
    except (InputFormatError, DataFlashReadError) as exc:
        return ConversionOutcome(ok=False, message=str(exc), error_code=EXIT_INPUT)
    except (UnsupportedFormatCharError, TimeOrderError, Df2UlogError) as exc:
        return ConversionOutcome(ok=False, message=str(exc), error_code=EXIT_CONVERT)
    except Exception as exc:  # noqa: BLE001 - GUI must always show a message, never crash
        return ConversionOutcome(
            ok=False, message=f"未预期的错误：{exc}", error_code=EXIT_CONVERT
        )


# ---------------------------------------------------------------------------
# Batch conversion (queue of files; sequential, cancellable, skip existing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchRequest:
    sources: tuple[Path, ...]
    output_dir: Path | None = None
    overwrite: bool = False
    verify: bool = False
    report_json: bool = False
    report_txt: bool = False
    params_mode: str = "initial"
    keep_logging: bool = True
    strict: bool = False
    allow_time_reset: bool = False

    def conversion_request_for(self, source: Path) -> ConversionRequest:
        return ConversionRequest(
            source=source,
            output_dir=self.output_dir,
            overwrite=self.overwrite,
            verify=self.verify,
            report_json=self.report_json,
            report_txt=self.report_txt,
            params_mode=self.params_mode,
            keep_logging=self.keep_logging,
            strict=self.strict,
            allow_time_reset=self.allow_time_reset,
        )


@dataclass(frozen=True)
class BatchItemResult:
    source: Path
    status: str  # "success" | "skipped" | "failed" | "cancelled"
    message: str = ""
    error_code: int = 0
    output_path: Path | None = None
    result: ConversionResult | None = None
    verify_ok: bool | None = None
    elapsed_s: float = 0.0


@dataclass(frozen=True)
class BatchOutcome:
    items: tuple[BatchItemResult, ...]
    cancelled: bool = False

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.status == "success")

    @property
    def skipped_count(self) -> int:
        return sum(1 for item in self.items if item.status == "skipped")

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")

    @property
    def cancelled_count(self) -> int:
        return sum(1 for item in self.items if item.status == "cancelled")

    @property
    def ok(self) -> bool:
        return self.failed_count == 0


BatchProgressCallback = Callable[[int, int, str, int], None]
BatchItemCallback = Callable[[int, BatchItemResult], None]
CancelCheck = Callable[[], bool]


def _run_batch_item(
    request: BatchRequest,
    source: Path,
    index: int,
    total: int,
    progress: BatchProgressCallback | None,
) -> BatchItemResult:
    started = time.perf_counter()
    conversion = request.conversion_request_for(source)
    output_path = output_path_for(conversion)
    if output_path.exists() and not request.overwrite:
        return BatchItemResult(
            source=source,
            status="skipped",
            message=f"输出已存在，已跳过：{output_path}",
            error_code=EXIT_OUTPUT,
            output_path=output_path,
            elapsed_s=time.perf_counter() - started,
        )
    file_progress = None
    if progress is not None:

        def file_progress(phase: str, percent: int) -> None:
            progress(index, total, phase, percent)

    outcome = run_conversion(conversion, progress=file_progress)
    if outcome.ok:
        status = "success"
    elif outcome.error_code == EXIT_OUTPUT:
        status = "skipped"
    else:
        status = "failed"
    if progress is not None:
        progress(index, total, "done", 100)
    return BatchItemResult(
        source=source,
        status=status,
        message=outcome.message,
        error_code=outcome.error_code,
        output_path=outcome.output_path,
        result=outcome.result,
        verify_ok=outcome.verify_ok,
        elapsed_s=time.perf_counter() - started,
    )


def run_batch(
    request: BatchRequest,
    progress: BatchProgressCallback | None = None,
    on_item: BatchItemCallback | None = None,
    should_cancel: CancelCheck | None = None,
) -> BatchOutcome:
    """Convert all sources sequentially; never raises for per-file failures."""
    items: list[BatchItemResult] = []
    total = len(request.sources)
    for index, source in enumerate(request.sources):
        if should_cancel is not None and should_cancel():
            for remaining in request.sources[index:]:
                items.append(
                    BatchItemResult(
                        source=remaining,
                        status="cancelled",
                        message="已取消（批量中止）",
                        error_code=EXIT_CONVERT,
                    )
                )
            return BatchOutcome(items=tuple(items), cancelled=True)
        item = _run_batch_item(request, source, index, total, progress)
        items.append(item)
        if on_item is not None:
            on_item(index, item)
    return BatchOutcome(items=tuple(items))


# ---------------------------------------------------------------------------
# Parameter scan (no conversion): read-only pass A, used by the parameters tab
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParamScanResult:
    path: Path
    source_format: str
    size: int
    firmware: str | None
    frame: str | None
    param_changes: tuple[tuple[str, float, int], ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParamScanOutcome:
    ok: bool
    message: str = ""
    error_code: int = 0
    result: ParamScanResult | None = None


def scan_params(source_path: Path) -> ParamScanOutcome:
    """Scan only metadata/PARM records; never writes an output file."""
    path = Path(source_path)
    if not path.is_file():
        return ParamScanOutcome(
            ok=False, message=f"input file not found: {path}", error_code=EXIT_INPUT
        )
    try:
        with DataFlashSource(path) as source:
            meta, _registry = scan_metadata(source)
        result = ParamScanResult(
            path=path,
            source_format=meta.source_format,
            size=path.stat().st_size,
            firmware=meta.firmware,
            frame=meta.frame,
            param_changes=tuple(meta.param_changes),
            warnings=tuple(meta.warnings),
        )
        return ParamScanOutcome(ok=True, result=result)
    except (InputFormatError, DataFlashReadError) as exc:
        return ParamScanOutcome(ok=False, message=str(exc), error_code=EXIT_INPUT)
    except Exception as exc:  # noqa: BLE001 - GUI shows a friendly message
        return ParamScanOutcome(
            ok=False, message=f"未预期的错误：{exc}", error_code=EXIT_CONVERT
        )
