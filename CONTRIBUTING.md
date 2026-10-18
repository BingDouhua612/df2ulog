# Contributing to df2ulog

Thanks for your interest! This document explains how to set up a development
environment, run the tests and submit changes.

## Development setup

Requirements: Python 3.10+ and `git`.

```bash
git clone https://github.com/BingDouhua612/df2ulog.git
cd df2ulog
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

Optional extras:

```bash
python -m pip install -e ".[verify,gui]"   # pyulog + PySide6
python -m pip install -e ".[gui-dev]"      # GUI dev/test/packaging tools
```

## Tests

```bash
ruff check src tests
pytest -q -m "not real"
```

`-m "not real"` runs the synthetic-fixture suite and is what CI runs. GUI
tests use Qt's offscreen platform and are skipped when PySide6 is not
installed:

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_gui_app.py -q
```

### Optional real-log acceptance tests

Tests marked `real` need local flight logs. They are **never** shipped with
the repository. Create `tests/real_logs.local.json` (git-ignored) or point
`DF2ULOG_REAL_LOGS_FILE` at a JSON file mapping roles to paths:

```json
{
  "bin_ref": "D:/logs/flight_01.BIN",
  "log_ref": "D:/logs/flight_01.log",
  "bin_a": "D:/logs/flight_02.BIN",
  "log_a": "D:/logs/flight_02.log"
}
```

Then run:

```bash
pytest -q -m real
```

See `tests/real_logs.example.json` for the expected shape. Missing files are
skipped automatically.

## Code style

- `ruff check src tests` must pass (config is in `pyproject.toml`).
- Keep the conversion pipeline streaming; avoid loading whole logs into memory.
- Output determinism is a hard requirement: same input + options must produce
  byte-identical `.ulg` files.
- Never commit real flight logs, `.ulg` outputs, `out/`, `dist/`, or `.venv/`.

## Submitting changes

1. Open an issue first for non-trivial changes.
2. Keep pull requests focused; add or update tests.
3. Run `ruff check src tests` and `pytest -q -m "not real"`.
4. Describe the change, motivation and verification in the PR template.
5. Do **not** attach real flight logs to issues/PRs; use the synthetic
   fixtures in `tests/fixtures/` or a minimized reproducer.

## Commit messages

Short imperative subject lines, e.g. `Fix ULog timestamp wrap at 2^32 ms`.
Reference issues with `Fixes #123` when applicable.
