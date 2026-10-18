"""PySide6 main window: dark UI, Chinese/English switch, batch queue, drag & drop."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .backend import (
    BatchItemResult,
    BatchOutcome,
    BatchRequest,
    ConversionOutcome,
    ConversionRequest,
    describe_source,
    output_path_for,
    run_batch,
)
from .i18n import LANG_EN, LANG_ZH, normalize_lang, tr
from .theme import apply_theme
from .widgets import GlyphIcon, app_icon, batch_summary_html, result_html

_ROW_KEYS = {
    "pending": "row.pending",
    "running": "row.running",
    "success": "row.success",
    "skipped": "row.skipped",
    "failed": "row.failed",
    "cancelled": "row.cancelled",
    "invalid": "row.invalid",
}
_STATUS_COLORS = {
    "pending": "#9fb0c3",
    "running": "#38bdf8",
    "success": "#34d399",
    "skipped": "#fbbf24",
    "failed": "#f87171",
    "cancelled": "#7d8b9c",
    "invalid": "#f87171",
}
_COLUMN_KEYS = (
    "table.file",
    "table.format",
    "table.size",
    "table.status",
    "table.elapsed",
    "table.detail",
)


class _TaskSignals(QObject):
    progress = Signal(int, int, str, int)
    item_done = Signal(int, object)
    finished = Signal(object)


class _BatchTask(QRunnable):
    """Runs ``run_batch`` on a QThreadPool worker; UI updates via signals."""

    def __init__(
        self,
        request: BatchRequest,
        signals: _TaskSignals,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._request = request
        self._signals = signals
        self._cancel_event = cancel_event

    def run(self) -> None:
        outcome = run_batch(
            self._request,
            progress=lambda index, total, phase, pct: self._signals.progress.emit(
                index, total, phase, pct
            ),
            on_item=lambda index, item: self._signals.item_done.emit(index, item),
            should_cancel=self._cancel_event.is_set,
        )
        self._signals.finished.emit(outcome)


class DropZone(QFrame):
    """Clickable, drag-highlightable drop target."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(76)
        self.setProperty("dragging", False)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._settings = QSettings("df2ulog", "df2ulog-gui")
        self._lang = normalize_lang(self._settings.value("language", LANG_ZH))
        self._i18n_labels: dict[str, QLabel] = {}
        self._i18n_buttons: dict[str, QWidget] = {}
        self._i18n_placeholders: dict[str, QWidget] = {}
        self._last_status: tuple[str, dict] = ("status.ready", {})
        self._rows: list[dict] = []
        self._row_sources: dict[Path, int] = {}
        self._batch_rows: list[int] = []
        self._last_output: Path | None = None
        self._last_batch_outcome: BatchOutcome | None = None
        self._last_single_outcome: ConversionOutcome | None = None
        self._busy = False
        self._cancel_event: threading.Event | None = None
        self._suppress_dialogs = (
            os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"
        )
        self._pool = QThreadPool.globalInstance()
        self.setWindowIcon(app_icon())
        self.setMinimumSize(780, 600)
        self.resize(880, 700)
        self.setAcceptDrops(True)
        self._build_ui()
        self._restore_settings()
        self._retranslate_ui()

    # ------------------------------------------------------------------ i18n
    def _t(self, key: str, **kwargs: object) -> str:
        return tr(key, self._lang, **kwargs)

    def _label(self, key: str, object_name: str | None = None, *, wrap: bool = False) -> QLabel:
        label = QLabel(self._t(key))
        if object_name:
            label.setObjectName(object_name)
        if wrap:
            label.setWordWrap(True)
        self._i18n_labels[key] = label
        return label

    def _button(self, key: str) -> QPushButton:
        button = QPushButton(self._t(key))
        self._i18n_buttons[key] = button
        return button

    def _checkbox(self, key: str) -> QCheckBox:
        box = QCheckBox(self._t(key))
        self._i18n_buttons[key] = box
        return box

    def _line_edit(self, key: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(self._t(key))
        self._i18n_placeholders[key] = edit
        return edit

    def _lang_button_text(self) -> str:
        return self._t("lang.switch_en") if self._lang == LANG_ZH else self._t("lang.switch_zh")

    def _toggle_language(self) -> None:
        self._lang = LANG_EN if self._lang == LANG_ZH else LANG_ZH
        self._settings.setValue("language", self._lang)
        self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(self._t("window.title", version=__version__))
        for key, label in self._i18n_labels.items():
            label.setText(self._t(key))
        for key, widget in self._i18n_buttons.items():
            if isinstance(widget, QCheckBox):
                widget.setText(self._t(key))
            else:
                widget.setText(self._t(key))
        for key, widget in self._i18n_placeholders.items():
            if isinstance(widget, QTextEdit):
                widget.setPlaceholderText(self._t(key))
            else:
                widget.setPlaceholderText(self._t(key))
        self.queue_table.setHorizontalHeaderLabels([self._t(key) for key in _COLUMN_KEYS])
        self.lang_button.setText(self._lang_button_text())
        self.lang_button.setToolTip(self._t("lang.tip"))
        self._refresh_queue()
        if self._last_batch_outcome is not None:
            self.result_text.setHtml(batch_summary_html(self._last_batch_outcome, self._lang))
            key, summary = self._batch_status(self._last_batch_outcome)
            self._set_status(key, summary=summary)
        elif self._last_single_outcome is not None:
            self.result_text.setHtml(result_html(self._last_single_outcome, self._lang))
            key, kwargs = self._last_status
            self._set_status(key, **kwargs)
        else:
            key, kwargs = self._last_status
            self._set_status(key, **kwargs)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 10, 18, 10)
        root.setSpacing(6)

        root.addLayout(self._build_header())

        self.drop_zone = DropZone()
        self.drop_zone.clicked.connect(self._choose_files)
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setContentsMargins(16, 6, 16, 6)
        drop_layout.setSpacing(0)
        drop_icon = GlyphIcon("download", 28)
        self.drop_label = self._label("drop.title", "DropTitle")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint = self._label("drop.hint", "Hint")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_icon_row = QHBoxLayout()
        drop_icon_row.addStretch(1)
        drop_icon_row.addWidget(drop_icon)
        drop_icon_row.addStretch(1)
        drop_layout.addWidget(self.drop_label)
        drop_layout.addWidget(drop_hint)
        drop_layout.addLayout(drop_icon_row)
        root.addWidget(self.drop_zone)

        self.source_label = QLabel("")
        self.source_label.setObjectName("Hint")
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)

        self.queue_table = QTableWidget(0, len(_COLUMN_KEYS))
        self.queue_table.setHorizontalHeaderLabels([self._t(key) for key in _COLUMN_KEYS])
        self.queue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.queue_table.setAlternatingRowColors(False)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setShowGrid(False)
        header = self.queue_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.queue_table.setColumnWidth(3, 80)
        self.queue_table.setColumnWidth(4, 64)
        self.queue_table.setMinimumHeight(96)
        queue_card = QFrame()
        queue_card.setObjectName("Card")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(8, 8, 8, 8)
        queue_layout.addWidget(self.queue_table)
        root.addWidget(queue_card, stretch=3)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.choose_button = self._button("button.add")
        self.choose_button.clicked.connect(self._choose_files)
        self.remove_button = self._button("button.remove")
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = self._button("button.clear")
        self.clear_button.clicked.connect(self._clear_queue)
        action_row.addWidget(self.choose_button)
        action_row.addWidget(self.remove_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        root.addWidget(self._build_output_card())

        convert_row = QHBoxLayout()
        convert_row.setSpacing(8)
        self.convert_button = self._button("button.convert")
        self.convert_button.setObjectName("Primary")
        self.convert_button.setMinimumHeight(42)
        self.convert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_button.setEnabled(False)
        self.convert_button.clicked.connect(self.start_conversion)
        self.cancel_button = self._button("button.cancel")
        self.cancel_button.setMinimumHeight(42)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_batch)
        convert_row.addWidget(self.convert_button, stretch=1)
        convert_row.addWidget(self.cancel_button)
        root.addLayout(convert_row)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_percent_label = QLabel("0%")
        self.progress_percent_label.setObjectName("Hint")
        self.progress_percent_label.setFixedWidth(40)
        self.progress_percent_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        progress_row.addWidget(self.progress_bar, stretch=1)
        progress_row.addWidget(self.progress_percent_label)
        root.addLayout(progress_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        result_card = QFrame()
        result_card.setObjectName("Card")
        result_layout = QVBoxLayout(result_card)
        result_layout.setContentsMargins(12, 8, 12, 8)
        result_layout.setSpacing(5)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setPlaceholderText(self._t("result.placeholder"))
        self._i18n_placeholders["result.placeholder"] = self.result_text
        self.result_text.setMinimumHeight(56)
        result_layout.addWidget(self.result_text, stretch=1)
        root.addWidget(result_card, stretch=2)

        self.open_folder_button = self._button("button.open_folder")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        root.addWidget(self.open_folder_button)

        self._set_status("status.ready")

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("df2ulog")
        title.setObjectName("Title")
        subtitle = self._label("header.subtitle", "Subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch(1)
        self.lang_button = QPushButton(self._lang_button_text())
        self.lang_button.setObjectName("LangSwitch")
        self.lang_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_button.setToolTip(self._t("lang.tip"))
        self.lang_button.clicked.connect(self._toggle_language)
        header.addWidget(self.lang_button, 0, Qt.AlignmentFlag.AlignVCenter)
        version_label = QLabel(f"v{__version__}")
        version_label.setObjectName("Hint")
        header.addWidget(version_label, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_output_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(5)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(9)
        dir_label = self._label("output.label", "FieldLabel")
        self.output_dir_edit = self._line_edit("output.placeholder")
        self.output_dir_edit.textChanged.connect(self._update_output_preview)
        self.output_dir_button = self._button("output.browse")
        self.output_dir_button.clicked.connect(self._choose_output_dir)
        dir_row.addWidget(dir_label)
        dir_row.addWidget(self.output_dir_edit, stretch=1)
        dir_row.addWidget(self.output_dir_button)
        layout.addLayout(dir_row)

        self.output_preview_label = QLabel("")
        self.output_preview_label.setObjectName("Hint")
        layout.addWidget(self.output_preview_label)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        options_label = self._label("options.label", "FieldLabel")
        self.verify_checkbox = self._checkbox("option.verify")
        self.verify_checkbox.setToolTip(self._t("option.verify.tip"))
        self.report_json_checkbox = self._checkbox("option.json")
        self.overwrite_checkbox = self._checkbox("option.overwrite")
        options_row.addWidget(options_label)
        options_row.addWidget(self.verify_checkbox)
        options_row.addWidget(self.report_json_checkbox)
        options_row.addWidget(self.overwrite_checkbox)
        options_row.addStretch(1)
        layout.addLayout(options_row)
        return card

    # ------------------------------------------------------------ drag/drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            self._set_drag_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_drag_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            return
        self.add_sources(paths)
        event.acceptProposedAction()

    def _set_drag_active(self, active: bool) -> None:
        if bool(self.drop_zone.property("dragging")) == active:
            return
        self.drop_zone.setProperty("dragging", active)
        style = self.drop_zone.style()
        style.unpolish(self.drop_zone)
        style.polish(self.drop_zone)
        self.drop_zone.update()

    # ------------------------------------------------------------ queue API
    def add_sources(self, paths: Sequence[Path]) -> None:
        added = 0
        for path in paths:
            source = Path(path)
            try:
                resolved = source.resolve()
            except OSError:
                resolved = source
            if resolved in self._row_sources:
                continue
            row: dict = {
                "source": source,
                "path": resolved,
                "fmt": "-",
                "size": 0,
                "status": "pending",
                "elapsed": "-",
                "message": "",
                "output": None,
                "result": None,
                "verify_ok": None,
                "error_code": 0,
            }
            try:
                info = describe_source(source)
                row["fmt"] = info.source_format
                row["size"] = info.size
            except Exception as exc:  # noqa: BLE001 - invalid rows stay visible
                row["status"] = "invalid"
                row["message"] = str(exc)
            self._row_sources[resolved] = len(self._rows)
            self._rows.append(row)
            added += 1
        self._refresh_queue()
        if added:
            self._set_status_state("")
            self._set_status("status.added", count=added)

    def set_sources(self, paths: Sequence[Path]) -> None:
        self._rows.clear()
        self._row_sources.clear()
        self._refresh_queue()
        self.add_sources(paths)

    def set_source(self, path: Path) -> None:
        self.set_sources([path])

    def _choose_files(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            self._t("dialog.choose_files"),
            str(Path.home()),
            self._t("dialog.file_filter"),
        )
        if paths:
            self.add_sources([Path(path) for path in paths])

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            self._t("dialog.choose_output"),
            self.output_dir_edit.text() or str(Path.home()),
        )
        if directory:
            self.output_dir_edit.setText(directory)

    def _remove_selected(self) -> None:
        if self._busy:
            return
        selected = sorted({index.row() for index in self.queue_table.selectedIndexes()}, reverse=True)
        for row_index in selected:
            del self._rows[row_index]
        self._reindex()
        self._refresh_queue()

    def _clear_queue(self) -> None:
        if self._busy:
            return
        self._rows.clear()
        self._row_sources.clear()
        self._last_output = None
        self._refresh_queue()

    def _reindex(self) -> None:
        self._row_sources = {row["path"]: index for index, row in enumerate(self._rows)}

    def _refresh_queue(self) -> None:
        self.queue_table.setRowCount(0)
        self.queue_table.setRowCount(len(self._rows))
        for index in range(len(self._rows)):
            self._paint_row(index)
        self._update_summary()
        self._update_output_preview()
        self._update_controls()

    def _paint_row(self, index: int) -> None:
        row = self._rows[index]
        status = row["status"]
        values = [
            row["source"].name,
            row["fmt"],
            f"{row['size']:,}" if row["size"] else "-",
            self._t(_ROW_KEYS.get(status, status)),
            row["elapsed"],
            str(row["output"]) if row["output"] else row["message"],
        ]
        for column, value in enumerate(values):
            item = self.queue_table.item(index, column)
            if item is None:
                item = QTableWidgetItem()
                self.queue_table.setItem(index, column, item)
            item.setText(value)
            item.setToolTip(value if column == 5 else "")
            if column == 3:
                item.setForeground(QColor(_STATUS_COLORS.get(status, "#9fb0c3")))
        self.queue_table.setRowHeight(index, 24)

    def _update_summary(self) -> None:
        if not self._rows:
            self.source_label.setText(self._t("queue.empty"))
            return
        last = self._rows[-1]
        if last["status"] == "invalid":
            self.source_label.setText(
                self._t(
                    "queue.summary.invalid",
                    name=last["source"].name,
                    message=last["message"][:80],
                )
            )
        else:
            self.source_label.setText(
                self._t(
                    "queue.summary",
                    count=len(self._rows),
                    name=last["source"].name,
                    fmt=last["fmt"],
                    size=last["size"],
                )
            )

    def _update_controls(self) -> None:
        has_valid = any(row["status"] != "invalid" for row in self._rows)
        self.convert_button.setEnabled(has_valid and not self._busy)
        self.choose_button.setEnabled(not self._busy)
        self.remove_button.setEnabled(not self._busy and bool(self._rows))
        self.clear_button.setEnabled(not self._busy and bool(self._rows))
        self.output_dir_button.setEnabled(not self._busy)
        self.cancel_button.setEnabled(self._busy)

    def _update_output_preview(self) -> None:
        valid_rows = [row for row in self._rows if row["status"] != "invalid"]
        if not valid_rows:
            self.output_preview_label.setText(self._t("output.none"))
            return
        directory = self.output_dir_edit.text().strip()
        first = valid_rows[0]["source"]
        request = ConversionRequest(
            source=first, output_dir=Path(directory) if directory else None
        )
        preview = output_path_for(request)
        suffix = self._t("output.exists_suffix") if preview.exists() else ""
        if directory:
            if len(valid_rows) > 1:
                self.output_preview_label.setText(
                    self._t(
                        "output.preview",
                        path=preview,
                        suffix=suffix,
                        count=len(valid_rows),
                    )
                )
            else:
                self.output_preview_label.setText(
                    self._t("output.preview.single", path=preview, suffix=suffix)
                )
        else:
            count_suffix = (
                self._t("output.count_suffix", count=len(valid_rows))
                if len(valid_rows) > 1
                else ""
            )
            self.output_preview_label.setText(
                self._t("output.same_dir", path=preview, suffix=suffix, count=count_suffix)
            )

    # -------------------------------------------------------------- actions
    def start_conversion(self) -> None:
        if self._busy:
            return
        valid_rows = [row for row in self._rows if row["status"] != "invalid"]
        if not valid_rows:
            return
        self._batch_rows = []
        for index, row in enumerate(self._rows):
            if row["status"] == "invalid":
                continue
            row["status"] = "pending"
            row["elapsed"] = "-"
            row["message"] = ""
            row["output"] = None
            row["result"] = None
            row["verify_ok"] = None
            row["error_code"] = 0
            self._batch_rows.append(index)
        self._last_batch_outcome = None
        self._last_single_outcome = None
        self._refresh_queue()
        directory = self.output_dir_edit.text().strip()
        request = BatchRequest(
            sources=tuple(self._rows[index]["source"] for index in self._batch_rows),
            output_dir=Path(directory) if directory else None,
            overwrite=self.overwrite_checkbox.isChecked(),
            verify=self.verify_checkbox.isChecked(),
            report_json=self.report_json_checkbox.isChecked(),
        )
        self._busy = True
        self._cancel_event = threading.Event()
        self._update_controls()
        self.progress_bar.setValue(0)
        self.progress_percent_label.setText("0%")
        self._set_status_state("")
        self._set_status("status.running")
        self.result_text.clear()
        signals = _TaskSignals(self)
        signals.progress.connect(self._apply_batch_progress)
        signals.item_done.connect(self._apply_item_result)
        signals.finished.connect(self._on_batch_finished)
        self._pool.start(_BatchTask(request, signals, self._cancel_event))

    def _cancel_batch(self) -> None:
        if not self._busy or self._cancel_event is None:
            return
        if self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.cancel_button.setEnabled(False)
        self._set_status("status.cancelling")

    def _on_batch_finished(self, outcome: BatchOutcome) -> None:
        self._busy = False
        self._cancel_event = None
        self._update_controls()
        self._apply_batch_outcome(outcome)

    def _phase_label(self, phase: str) -> str:
        return self._t(f"phase.{phase}")

    def _apply_batch_progress(self, index: int, total: int, phase: str, percent: int) -> None:
        if index >= len(self._batch_rows):
            return
        row_index = self._batch_rows[index]
        if self._rows[row_index]["status"] == "pending":
            self._rows[row_index]["status"] = "running"
            self._paint_row(row_index)
        self.progress_bar.setValue(percent)
        self.progress_percent_label.setText(f"{percent}%")
        self._set_status(
            "status.progress",
            index=index + 1,
            total=total,
            phase=self._phase_label(phase),
            percent=percent,
        )

    def _store_item(self, row: dict, item: BatchItemResult) -> None:
        row["status"] = item.status
        row["elapsed"] = f"{item.elapsed_s:.2f}s"
        row["message"] = item.message
        row["output"] = item.output_path
        row["result"] = item.result
        row["verify_ok"] = item.verify_ok
        row["error_code"] = item.error_code
        if item.output_path is not None and item.output_path.exists():
            self._last_output = item.output_path
            self.open_folder_button.setEnabled(True)

    def _apply_item_result(self, index: int, item: BatchItemResult) -> None:
        if index >= len(self._batch_rows):
            return
        row_index = self._batch_rows[index]
        self._store_item(self._rows[row_index], item)
        self._paint_row(row_index)

    def _batch_summary(self, outcome: BatchOutcome) -> str:
        return " · ".join(
            [
                f"{self._t('summary.success')} {outcome.success_count}",
                f"{self._t('summary.skipped')} {outcome.skipped_count}",
                f"{self._t('summary.failed')} {outcome.failed_count}",
            ]
        )

    def _batch_status(self, outcome: BatchOutcome) -> tuple[str, str]:
        summary = self._batch_summary(outcome)
        if outcome.failed_count:
            return "status.batch_done_failed", summary
        if outcome.cancelled:
            return "status.batch_cancelled", summary
        return "status.batch_done", summary

    def _apply_batch_outcome(self, outcome: BatchOutcome) -> None:
        row_indices = self._batch_rows or [
            index for index, row in enumerate(self._rows) if row["status"] != "invalid"
        ]
        for index, item in enumerate(outcome.items):
            if index >= len(row_indices):
                break
            row_index = row_indices[index]
            self._store_item(self._rows[row_index], item)
            self._paint_row(row_index)
        self._last_batch_outcome = outcome
        self._last_single_outcome = None
        self.result_text.setHtml(batch_summary_html(outcome, self._lang))
        self.progress_bar.setValue(100)
        self.progress_percent_label.setText("100%")
        self.open_folder_button.setEnabled(self._last_output is not None)
        status_key, summary = self._batch_status(outcome)
        if outcome.failed_count:
            self._set_status_state("error")
        elif outcome.cancelled:
            self._set_status_state("")
        else:
            self._set_status_state("success")
        self._set_status(status_key, summary=summary)
        self._update_output_preview()

    # ------------------------------------------------- legacy single helpers
    def _apply_progress(self, phase: str, percent: int) -> None:
        self.progress_bar.setValue(percent)
        self.progress_percent_label.setText(f"{percent}%")
        self.status_label.setText(f"{self._phase_label(phase)} … {percent}%")

    def _result_text(self, outcome: ConversionOutcome) -> str:
        lines = [self._t("result.single_output", path=outcome.output_path)]
        result = outcome.result
        if result is not None:
            lines.extend(
                [
                    self._t("result.single_topic", count=len(result.topics)),
                    self._t("result.single_records", count=result.data_record_count),
                    f"{self._t('result.sha256')}: {result.output_sha256}",
                ]
            )
        return "\n".join(lines)

    def _apply_outcome(self, outcome: ConversionOutcome) -> None:
        if self._rows:
            row = self._rows[-1]
            self._store_item(
                row,
                BatchItemResult(
                    source=row["source"],
                    status="success" if outcome.ok else "failed",
                    message=outcome.message,
                    error_code=outcome.error_code,
                    output_path=outcome.output_path,
                    result=outcome.result,
                    verify_ok=outcome.verify_ok,
                ),
            )
            self._paint_row(len(self._rows) - 1)
        self._last_single_outcome = outcome
        self._last_batch_outcome = None
        if outcome.ok:
            self.progress_bar.setValue(100)
            self.progress_percent_label.setText("100%")
            self._set_status_state("success")
            self._set_status("status.single_done")
            self.result_text.setHtml(result_html(outcome, self._lang))
            self.open_folder_button.setEnabled(outcome.output_path is not None)
            if outcome.output_path is not None:
                self._last_output = outcome.output_path
                self._settings.setValue("last_output_dir", str(outcome.output_path.parent))
            self._update_output_preview()
            return
        self._set_status_state("error")
        self._set_status(
            "status.single_failed", code=outcome.error_code, message=outcome.message
        )
        if outcome.result is not None:
            self.result_text.setPlainText(self._result_text(outcome))
        self._show_error(
            self._t("dialog.error_title"),
            self._t(
                "dialog.error_body",
                message=outcome.message,
                code=outcome.error_code,
            ),
        )

    def _open_output_folder(self) -> None:
        target = self._last_output
        if target is None:
            if not self._rows:
                return
            directory = self.output_dir_edit.text().strip()
            request = ConversionRequest(
                source=self._rows[0]["source"],
                output_dir=Path(directory) if directory else None,
            )
            target = output_path_for(request)
        folder = target.parent if target.suffix == ".ulg" else target
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -------------------------------------------------------------- helpers
    def _set_status(self, key: str, **kwargs: object) -> None:
        self._last_status = (key, kwargs)
        self.status_label.setText(self._t(key, **kwargs))

    def _set_status_state(self, state: str) -> None:
        self.status_label.setProperty("state", state)
        style = self.status_label.style()
        style.unpolish(self.status_label)
        style.polish(self.status_label)
        self.status_label.update()

    def _show_error(self, title: str, text: str) -> None:
        if not self._suppress_dialogs:
            QMessageBox.critical(self, title, text)

    def _restore_settings(self) -> None:
        last = str(self._settings.value("last_output_dir", "") or "")
        if last:
            self.output_dir_edit.setText(last)
        self._update_output_preview()

    def closeEvent(self, event) -> None:
        if self._busy:
            self.status_label.setText(self._t("status.close_guard"))
            event.ignore()
            return
        super().closeEvent(event)


def main(argv: Sequence[str] | None = None) -> int:
    app = QApplication(list(argv) if argv is not None else sys.argv)
    app.setApplicationName("df2ulog-gui")
    apply_theme(app)
    window = MainWindow()
    window.show()
    return app.exec()
