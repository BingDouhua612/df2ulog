# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- GUI language switch (Chinese / English) in the top-right corner; the
  choice is persisted with `QSettings`.
- Bilingual README (`README.md` / `README.en.md`).
- Hand-drawn `.bin/.log to ulog` app icon (window icon + packaged exe icon,
  multi-resolution `.ico`).

## [0.1.0] - 2026-10-18

### Added

- DataFlash `.BIN` reader (via `pymavlink.DFReader`) and Mission Planner text
  `.log` reader with content-based format detection.
- Streaming PX4 ULog v1 writer (header, B/I/F/P/A/D/L/S records) that produces
  `pyulog`-readable files without `file_corruption`.
- FMT/FMTU-driven topic planning, multi-instance topics, unit tables and
  field-type conversion.
- `df2ulog` CLI: `convert`, `inspect`, `verify` with stable exit codes.
- Optional `verify` subcommand and `--verify` option: lint + `pyulog` read-back
  + full source replay comparison.
- Deterministic output (same input + options → byte-identical `.ulg`).
- Reports in plain text and JSON (`--report`, `--report-json`).
- Minimal Qt-free GUI backend and `--selftest` headless entry point.
- PySide6 desktop GUI (`df2ulog-gui`): dark theme, drag & drop, output preview,
  background conversion, progress and result panel.
- **Batch conversion** in the GUI: queue of files, sequential conversion,
  per-file status/elapsed time, cancel-remaining, skip-existing policy and
  batch summary.
- PyInstaller `onedir` packaging script for a Python-free Windows executable.
- Documentation: format notes, mapping notes, GUI guide, decision records and
  acceptance records.
- Test suite: synthetic fixtures, ULog codec/writer/linter tests, converter and
  verifier tests, GUI tests (offscreen), plus optional real-log acceptance
  tests enabled through `DF2ULOG_REAL_LOGS_FILE`.

[0.1.0]: https://github.com/BingDouhua612/df2ulog/releases/tag/v0.1.0
