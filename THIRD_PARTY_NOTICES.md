# Third-party notices

`df2ulog` is MIT-licensed. It depends on the following third-party projects;
their licenses apply to their own code and are **not** relicensed by this
project.

## Runtime dependencies

| Package | License | Purpose | Link |
|---|---|---|---|
| `pymavlink` | LGPL-3.0 | Parsing ArduPilot DataFlash `.BIN` files (`pymavlink.DFReader`) | <https://github.com/ArduPilot/pymavlink> |

## Optional dependencies

| Package | License | Purpose | Link |
|---|---|---|---|
| `pyulog` | BSD-3-Clause | Independent ULog reader used by `verify` and by tests | <https://github.com/PX4/pyulog> |
| `PySide6` / Qt for Python | LGPL-3.0-only (also available under GPL-2.0/3.0) | Desktop GUI | <https://www.qt.io/qt-for-python> |

## Build-only tools

| Package | License | Purpose |
|---|---|---|
| `PyInstaller` | GPL-2.0-or-later with bootloader exception | Freezing the optional GUI executable |
| `pytest`, `ruff` | MIT | Tests and linting (development only) |

## Notes on binary distribution

If you redistribute a packaged build (for example the PyInstaller `onedir`
GUI), you must comply with the LGPL for `PySide6`/Qt and `pymavlink`:

- include the full license texts of the LGPL-licensed components;
- keep the `onedir` layout so users can replace the bundled libraries;
- make the corresponding source code of those components available (upstream
  links above are sufficient for unmodified releases).

`PlotJuggler` is **not** bundled with this project. It is only mentioned as a
compatible viewer of the generated `.ulg` files.
