"""Parameter-view tab: drop a log, scan PARM records only (no .ulg output)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .backend import ParamScanOutcome, scan_params
from .i18n import LANG_ZH, normalize_lang, tr
from .params_view import ParamTableView
from .widgets import DropZone, GlyphIcon


class _ScanSignals(QObject):
    done = Signal(object, object)  # Path, ParamScanOutcome
    finished = Signal()


class _ScanTask(QRunnable):
    def __init__(self, path: Path, signals: _ScanSignals) -> None:
        super().__init__()
        self._path = path
        self._signals = signals

    def run(self) -> None:
        outcome = scan_params(self._path)
        self._signals.done.emit(self._path, outcome)
        self._signals.finished.emit()


class ParamScanPage(QWidget):
    """A dedicated page for inspecting parameters without converting."""

    def __init__(self, lang: str = LANG_ZH, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lang = normalize_lang(lang)
        self._paths: list[Path] = []
        self._results: dict[Path, ParamScanOutcome] = {}
        self._pending: list[Path] = []
        self._busy = False
        self._scanned = 0
        self._pool = QThreadPool.globalInstance()
        self._build_ui()

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(key, self._lang, **kwargs)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 6, 0, 0)
        root.setSpacing(6)

        self.drop_zone = DropZone()
        self.drop_zone.setFixedHeight(96)
        self.drop_zone.clicked.connect(self._choose_files)
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(16, 8, 16, 8)
        drop_layout.setSpacing(0)
        self.drop_label = QLabel(self._t("params.drop.title"))
        self.drop_label.setObjectName("DropTitle")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint = QLabel(self._t("params.drop.hint"))
        self.drop_hint.setObjectName("Hint")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_row = QHBoxLayout()
        icon_row.addStretch(1)
        icon_row.addWidget(GlyphIcon("download", 28))
        icon_row.addStretch(1)
        drop_layout.addWidget(self.drop_label)
        drop_layout.addWidget(self.drop_hint)
        drop_layout.addLayout(icon_row)
        root.addWidget(self.drop_zone)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.add_button = QPushButton(self._t("params.add"))
        self.add_button.clicked.connect(self._choose_files)
        self.file_combo = QComboBox()
        self.file_combo.currentIndexChanged.connect(self._show_current)
        self.status_label = QLabel(self._t("params.no_files"))
        self.status_label.setObjectName("Hint")
        row.addWidget(self.add_button)
        row.addWidget(self.file_combo, stretch=1)
        row.addWidget(self.status_label)
        root.addLayout(row)

        self.table_view = ParamTableView(self, self._lang)
        root.addWidget(self.table_view, stretch=1)

    # -------------------------------------------------------------- actions
    def _choose_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            self._t("params.choose"),
            str(Path.home()),
            self._t("dialog.file_filter"),
        )
        if paths:
            self.add_files([Path(path) for path in paths])

    def add_files(self, paths: list[Path]) -> None:
        added = 0
        for path in paths:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in self._paths:
                continue
            self._paths.append(resolved)
            self.file_combo.addItem(resolved.name)
            self._pending.append(resolved)
            added += 1
        if added:
            self._set_status(self._t("params.queued", count=len(self._pending)))
            self._start_next()

    def _start_next(self) -> None:
        if self._busy or not self._pending:
            return
        path = self._pending.pop(0)
        self._busy = True
        self._set_status(self._t("params.scanning", name=path.name))
        signals = _ScanSignals(self)
        signals.done.connect(self._on_scanned)
        signals.finished.connect(self._on_finished)
        self._pool.start(_ScanTask(path, signals))

    def _on_scanned(self, path: object, outcome: object) -> None:
        source = Path(path)  # type: ignore[arg-type]
        result = outcome  # type: ignore[assignment]
        if not isinstance(result, ParamScanOutcome):
            return
        self._results[source] = result
        self._scanned += 1
        if source in self._paths:
            index = self._paths.index(source)
            if result.ok and result.result is not None:
                self.file_combo.setItemText(
                    index,
                    self._t(
                        "params.file_item",
                        name=source.name,
                        count=len(result.result.param_changes),
                    ),
                )
            else:
                self.file_combo.setItemText(
                    index, self._t("params.file_item_error", name=source.name)
                )
            if self.file_combo.currentIndex() == index:
                self._show_current()

    def _on_finished(self) -> None:
        self._busy = False
        if self._pending:
            self._start_next()
            return
        self._set_status(self._t("params.ready", count=self._scanned))

    def _show_current(self) -> None:
        if not self._paths:
            self.table_view.set_entries([])
            return
        index = max(0, self.file_combo.currentIndex())
        path = self._paths[index]
        outcome = self._results.get(path)
        if outcome is None:
            self.table_view.set_entries([])
            self._set_status(self._t("params.scanning", name=path.name))
            return
        if not outcome.ok or outcome.result is None:
            self.table_view.set_entries([])
            self._set_status(
                self._t("params.scan_error", name=path.name, message=outcome.message)
            )
            return
        self.table_view.set_entries(outcome.result.param_changes)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # ------------------------------------------------------------------ i18n
    def set_language(self, lang: str) -> None:
        self._lang = normalize_lang(lang)
        self.drop_label.setText(self._t("params.drop.title"))
        self.drop_hint.setText(self._t("params.drop.hint"))
        self.add_button.setText(self._t("params.add"))
        self.table_view.set_language(self._lang)
        for index, path in enumerate(self._paths):
            outcome = self._results.get(path)
            if outcome is None:
                self.file_combo.setItemText(index, path.name)
            elif outcome.ok and outcome.result is not None:
                self.file_combo.setItemText(
                    index,
                    self._t(
                        "params.file_item",
                        name=path.name,
                        count=len(outcome.result.param_changes),
                    ),
                )
            else:
                self.file_combo.setItemText(
                    index, self._t("params.file_item_error", name=path.name)
                )
        if not self._paths:
            self._set_status(self._t("params.no_files"))
        self._show_current()
