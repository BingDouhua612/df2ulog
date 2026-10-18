"""Headless entry points first; Qt is imported lazily for the GUI path."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .. import __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="df2ulog-gui")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument(
        "--selftest",
        metavar="FILE",
        help="convert FILE headlessly and exit (packaging smoke test)",
    )
    parser.add_argument(
        "-o", "--output", metavar="DIR", help="output directory for --selftest"
    )
    return parser


def _reconfigure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - exotic streams
            pass


def _print_line(text: str) -> None:
    """Print when a console exists; windowed (pythonw) builds may have stdout=None."""
    stream = sys.stdout
    if stream is None:
        return
    try:
        print(text, file=stream)
    except OSError:  # pragma: no cover - detached console
        pass


def main(argv: Sequence[str] | None = None) -> int:
    _reconfigure_stdout()
    args = _parser().parse_args(argv)
    if args.version:
        _print_line(f"df2ulog-gui {__version__}")
        return 0
    if args.selftest:
        from .backend import ConversionRequest, run_conversion

        request = ConversionRequest(
            source=Path(args.selftest),
            output_dir=Path(args.output) if args.output else None,
            overwrite=True,
        )
        outcome = run_conversion(request)
        _print_line(outcome.message)
        return 0 if outcome.ok else (outcome.error_code or 1)
    from .app import main as app_main

    return app_main(argv)


if __name__ == "__main__":
    sys.exit(main())
