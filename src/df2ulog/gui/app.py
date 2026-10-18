"""PySide6 main window: dark professional UI, batch queue, drag & drop, progress."""

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
from .theme import apply_theme
from .widgets import GlyphIcon, app_icon, batch_summary_html, result_html

_PHASE_LABELS = {
    "scan": "扫描元数据",
    "planned": "规划 topic",
    "definitions": "写定义段",
    "write": "写数据",
    "done": "完成",
}

_STATUS_LABELS = {
    "pending": "等待中",
    "running": "转换中",
    "success": "成功",
    "skipped": "跳过",
    "failed": "失败",
    "cancelled": "已取消",
    "invalid": "无效",
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

_COLUMNS = ("文件", "格式", "大小", "状态", "耗时", "输出 / 说明")


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
        self.setWindowTitle(f"df2ulog {__version__} — DataFlash → ULog 批量转换器")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(780, 600)
        self.resize(880, 700)
        self.setAcceptDrops(True)
        self._rows: list[dict] = []
        self._row_sources: dict[Path, int] = {}
        self._batch_rows: list[int] = []
        self._last_output: Path | None = None
        self._busy = False
        self._cancel_event: threading.Event | None = None
        self._suppress_dialogs = (
            os.environ.get("QT_QPA_PLATFORM", "").lower() == "offscreen"
        )
        self._settings = QSettings("df2ulog", "df2ulog-gui")
        self._pool = QThreadPool.globalInstance()
        self._build_ui()
        self._restore_settings()

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
        self.drop_label = QLabel("拖入一个或多个 DataFlash 日志")
        self.drop_label.setObjectName("DropTitle")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_hint = QLabel("支持 .BIN / .log（按内容识别）· 多次拖入会追加到队列")
        drop_hint.setObjectName("Hint")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_icon_row = QHBoxLayout()
        drop_icon_row.addStretch(1)
        drop_icon_row.addWidget(drop_icon)
        drop_icon_row.addStretch(1)
        drop_layout.addWidget(self.drop_label)
        drop_layout.addWidget(drop_hint)
        drop_layout.addLayout(drop_icon_row)
        root.addWidget(self.drop_zone)

        self.source_label = QLabel("未选择文件")
        self.source_label.setObjectName("Hint")
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)

        self.queue_table = QTableWidget(0, len(_COLUMNS))
        self.queue_table.setHorizontalHeaderLabels(list(_COLUMNS))
        self.queue_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.queue_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
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
        self.queue_table.setColumnWidth(3, 72)
        self.queue_table.setColumnWidth(4, 64)
        self.queue_table.setMinimumHeight(112)
        queue_card = QFrame()
        queue_card.setObjectName("Card")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(8, 8, 8, 8)
        queue_layout.addWidget(self.queue_table)
        root.addWidget(queue_card, stretch=3)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.choose_button = QPushButton("添加文件…")
        self.choose_button.clicked.connect(self._choose_files)
        self.remove_button = QPushButton("移除选中")
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self._clear_queue)
        action_row.addWidget(self.choose_button)
        action_row.addWidget(self.remove_button)
        action_row.addWidget(self.clear_button)
        action_row.addStretch(1)
        root.addLayout(action_row)

        root.addWidget(self._build_output_card())

        convert_row = QHBoxLayout()
        convert_row.setSpacing(8)
        self.convert_button = QPushButton("开始批量转换")
        self.convert_button.setObjectName("Primary")
        self.convert_button.setMinimumHeight(42)
        self.convert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_button.setEnabled(False)
        self.convert_button.clicked.connect(self.start_conversion)
        self.cancel_button = QPushButton("取消")
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

        self.status_label = QLabel("就绪 · 拖入一个或多个日志文件开始")
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
        self.result_text.setPlaceholderText(
            "批量结果会显示在这里：成功 / 跳过 / 失败统计与失败原因 …"
        )
        result_layout.addWidget(self.result_text, stretch=1)
        self.result_text.setMinimumHeight(56)
        root.addWidget(result_card, stretch=2)

        self.open_folder_button = QPushButton("打开所在文件夹")
        self.open_folder_button.setEnabled(False)
        self.open_folder_button.clicked.connect(self._open_output_folder)
        root.addWidget(self.open_folder_button)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        title = QLabel("df2ulog")
        title.setObjectName("Title")
        subtitle = QLabel("ArduPilot DataFlash → PX4 ULog 批量转换器")
        subtitle.setObjectName("Subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch(1)
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
        dir_label = QLabel("输出目录")
        dir_label.setObjectName("FieldLabel")
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setPlaceholderText("留空 = 每个文件输出到各自所在目录")
        self.output_dir_edit.textChanged.connect(self._update_output_preview)
        self.output_dir_button = QPushButton("浏览…")
        self.output_dir_button.clicked.connect(self._choose_output_dir)
        dir_row.addWidget(dir_label)
        dir_row.addWidget(self.output_dir_edit, stretch=1)
        dir_row.addWidget(self.output_dir_button)
        layout.addLayout(dir_row)

        self.output_preview_label = QLabel("输出：—")
        self.output_preview_label.setObjectName("Hint")
        layout.addWidget(self.output_preview_label)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        options_label = QLabel("选项")
        options_label.setObjectName("FieldLabel")
        self.verify_checkbox = QCheckBox("转换后校验 (verify)")
        self.verify_checkbox.setToolTip(
            "对每个输出做 lint + pyulog 回读 + 源文件全量重放比对（批量会明显变慢）"
        )
        self.report_json_checkbox = QCheckBox("生成 JSON 报告")
        self.overwrite_checkbox = QCheckBox("覆盖已存在文件（否则跳过）")
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
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
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
        self._refresh_queue()
        if self._rows:
            self._set_status_state("")
            self.status_label.setText(
                f"已加入 {len(paths)} 个文件；点击「开始批量转换」。"
            )

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
            "选择 DataFlash 日志（可多选）",
            str(Path.home()),
            "DataFlash 日志 (*.BIN *.bin *.log);;所有文件 (*)",
        )
        if paths:
            self.add_sources([Path(path) for path in paths])

    def _choose_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "选择输出目录（留空=各文件所在目录）",
            self.output_dir_edit.text() or str(Path.home()),
        )
        if directory:
            self.output_dir_edit.setText(directory)

    def _remove_selected(self) -> None:
        if self._busy:
            return
        selected = sorted(
            {index.row() for index in self.queue_table.selectedIndexes()},
            reverse=True,
        )
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
        self._row_sources = {
            row["path"]: index for index, row in enumerate(self._rows)
        }

    def _refresh_queue(self) -> None:
        self.queue_table.setRowCount(0)
        self.queue_table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
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
            _STATUS_LABELS.get(status, status),
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
            self.source_label.setText("未选择文件")
            return
        last = self._rows[-1]
        if last["status"] == "invalid":
            hint = f"最近：{last['source'].name}（无效：{last['message'][:80]}）"
        else:
            hint = (
                f"最近：{last['source'].name}（{last['fmt']}，{last['size']:,} B）"
            )
        self.source_label.setText(f"已选择 {len(self._rows)} 个文件 · {hint}")

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
            self.output_preview_label.setText("输出：—")
            return
        directory = self.output_dir_edit.text().strip()
        first = valid_rows[0]["source"]
        request = ConversionRequest(
            source=first,
            output_dir=Path(directory) if directory else None,
        )
        preview = output_path_for(request)
        suffix = "（已存在，转换需勾选覆盖）" if preview.exists() else ""
        count = f" · 共 {len(valid_rows)} 个文件" if len(valid_rows) > 1 else ""
        if directory:
            self.output_preview_label.setText(f"输出：{preview}{suffix}{count}")
        else:
            self.output_preview_label.setText(
                f"输出：各文件同目录 · 如 {preview}{suffix}{count}"
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
        self.status_label.setText("批量转换中…")
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
        self.status_label.setText("正在取消：当前文件完成后将停止后续文件…")

    def _on_batch_finished(self, outcome: BatchOutcome) -> None:
        self._busy = False
        self._cancel_event = None
        self._update_controls()
        self._apply_batch_outcome(outcome)

    def _apply_batch_progress(
        self, index: int, total: int, phase: str, percent: int
    ) -> None:
        if index >= len(self._batch_rows):
            return
        row_index = self._batch_rows[index]
        if self._rows[row_index]["status"] == "pending":
            self._rows[row_index]["status"] = "running"
            self._paint_row(row_index)
        self.progress_bar.setValue(percent)
        self.progress_percent_label.setText(f"{percent}%")
        self.status_label.setText(
            f"文件 {index + 1}/{total} · {_PHASE_LABELS.get(phase, phase)} … {percent}%"
        )

    def _apply_item_result(self, index: int, item: BatchItemResult) -> None:
        if index >= len(self._batch_rows):
            return
        row_index = self._batch_rows[index]
        row = self._rows[row_index]
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
        self._paint_row(row_index)

    def _apply_batch_outcome(self, outcome: BatchOutcome) -> None:
        row_indices = self._batch_rows or [
            index
            for index, row in enumerate(self._rows)
            if row["status"] != "invalid"
        ]
        for index, item in enumerate(outcome.items):
            if index >= len(row_indices):
                break
            row_index = row_indices[index]
            row = self._rows[row_index]
            row["status"] = item.status
            row["elapsed"] = f"{item.elapsed_s:.2f}s"
            row["message"] = item.message
            row["output"] = item.output_path
            row["result"] = item.result
            row["verify_ok"] = item.verify_ok
            row["error_code"] = item.error_code
            if item.output_path is not None and item.output_path.exists():
                self._last_output = item.output_path
            self._paint_row(row_index)
        self.result_text.setHtml(batch_summary_html(outcome))
        parts = [
            f"成功 {outcome.success_count}",
            f"跳过 {outcome.skipped_count}",
            f"失败 {outcome.failed_count}",
        ]
        if outcome.cancelled:
            parts.append("已取消")
        summary = "批量完成：" + " · ".join(parts)
        if outcome.failed_count:
            self._set_status_state("error")
            self.status_label.setText("批量结束（有失败）：" + " · ".join(parts))
        elif outcome.cancelled:
            self._set_status_state("")
            self.status_label.setText(summary)
        else:
            self._set_status_state("success")
            self.status_label.setText(summary + " ✓")
        self.progress_bar.setValue(100)
        self.progress_percent_label.setText("100%")
        self.open_folder_button.setEnabled(self._last_output is not None)
        self._update_output_preview()

    # ------------------------------------------------- legacy single helpers
    def _apply_progress(self, phase: str, percent: int) -> None:
        self.progress_bar.setValue(percent)
        self.progress_percent_label.setText(f"{percent}%")
        self.status_label.setText(f"{_PHASE_LABELS.get(phase, phase)} … {percent}%")

    def _apply_outcome(self, outcome: ConversionOutcome) -> None:
        if self._rows:
            row = self._rows[-1]
            row["status"] = "success" if outcome.ok else "failed"
            row["message"] = outcome.message
            row["output"] = outcome.output_path
            row["result"] = outcome.result
            row["verify_ok"] = outcome.verify_ok
            row["error_code"] = outcome.error_code
            self._paint_row(len(self._rows) - 1)
        if outcome.ok:
            self.progress_bar.setValue(100)
            self.progress_percent_label.setText("100%")
            self._set_status_state("success")
            self.status_label.setText("转换完成 ✓")
            self.result_text.setHtml(result_html(outcome))
            self.open_folder_button.setEnabled(outcome.output_path is not None)
            if outcome.output_path is not None:
                self._last_output = outcome.output_path
                self._settings.setValue(
                    "last_output_dir", str(outcome.output_path.parent)
                )
            self._update_output_preview()
            return
        self._set_status_state("error")
        self.status_label.setText(
            f"失败（错误码 {outcome.error_code}）：{outcome.message}"
        )
        if outcome.result is not None:
            self.result_text.setPlainText(self._result_text(outcome))
        self._show_error(
            "转换失败",
            f"{outcome.message}\n\n错误码：{outcome.error_code}\n"
            "（3 输入无效 / 4 转换失败 / 5 verify 失败 / 6 输出已存在）",
        )

    def _result_text(self, outcome: ConversionOutcome) -> str:
        lines = [f"输出：{outcome.output_path}"]
        result = outcome.result
        if result is not None:
            lines.extend(
                [
                    f"topic：{len(result.topics)}",
                    f"数据记录：{result.data_record_count:,}",
                    f"输出 SHA256：{result.output_sha256}",
                ]
            )
        return "\n".join(lines)

    # -------------------------------------------------------------- helpers
    def _open_output_folder(self) -> None:
        target = self._last_output
        if target is None:
            if not self._rows:
                return
            request = ConversionRequest(
                source=self._rows[0]["source"],
                output_dir=(
                    Path(self.output_dir_edit.text().strip())
                    if self.output_dir_edit.text().strip()
                    else None
                ),
            )
            target = output_path_for(request)
        folder = target.parent if target.suffix == ".ulg" else target
        if folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

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
            self.status_label.setText("转换进行中，请等待完成或点击「取消」后再关闭窗口。")
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
