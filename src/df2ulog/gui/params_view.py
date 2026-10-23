"""Parameter-change table dialog for the GUI (all PARM records)."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .i18n import LANG_ZH, normalize_lang, tr

ParamEntry = tuple[str, float, int]  # name, value, time_us


class ParamTableDialog(QDialog):
    """Table of every PARM record, with search and copy.

    ``files`` is a list of ``(label, entries)`` so a batch conversion can show
    one table with a file selector.
    """

    def __init__(
        self,
        parent=None,
        files: Sequence[tuple[str, Sequence[ParamEntry]]] | None = None,
        lang: str = LANG_ZH,
    ) -> None:
        super().__init__(parent)
        self._lang = normalize_lang(lang)
        self._files = [(label, list(entries)) for label, entries in (files or [])]
        self.setWindowTitle(self._t("params.title"))
        self.resize(780, 540)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        if len(self._files) > 1:
            top.addWidget(QLabel(self._t("params.file")))
        self.file_combo = QComboBox()
        for label, _entries in self._files:
            self.file_combo.addItem(label)
        self.file_combo.currentIndexChanged.connect(self._populate)
        top.addWidget(self.file_combo, stretch=1)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self._t("params.search"))
        self.search_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.search_edit, stretch=2)
        root.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            [
                self._t("params.col.index"),
                self._t("params.col.name"),
                self._t("params.col.value"),
                self._t("params.col.time"),
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, stretch=1)

        bottom = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setObjectName("Hint")
        bottom.addWidget(self.count_label, stretch=1)
        self.copy_button = QPushButton(self._t("params.copy"))
        self.copy_button.clicked.connect(self._copy_all)
        self.close_button = QPushButton(self._t("params.close"))
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.copy_button)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self._populate()

    # ------------------------------------------------------------------ i18n
    def _t(self, key: str, **kwargs: object) -> str:
        return tr(key, self._lang, **kwargs)

    # ----------------------------------------------------------------- table
    def _entries(self) -> list[ParamEntry]:
        if not self._files:
            return []
        index = max(0, self.file_combo.currentIndex())
        return self._files[index][1]

    def _populate(self) -> None:
        entries = self._entries()
        self.table.setRowCount(0)
        self.table.setRowCount(len(entries))
        for row, (name, value, time_us) in enumerate(entries):
            cells = (
                str(row + 1),
                name,
                f"{value:g}",
                f"{time_us / 1_000_000:.3f}",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column in (0, 2, 3):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                item.setToolTip(f"{time_us} us")
                self.table.setItem(row, column, item)
        names = len({entry[0] for entry in entries})
        if entries:
            self.count_label.setText(
                self._t("params.count", records=len(entries), names=names)
            )
        else:
            self.count_label.setText(self._t("params.empty"))
        self._apply_filter(self.search_edit.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row, False)
                continue
            name_item = self.table.item(row, 1)
            value_item = self.table.item(row, 2)
            haystack = " ".join(
                item.text() for item in (name_item, value_item) if item is not None
            ).lower()
            self.table.setRowHidden(row, needle not in haystack)

    def _rows_as_text(self) -> str:
        lines = []
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            cells = [
                self.table.item(row, column).text()
                for column in range(self.table.columnCount())
                if self.table.item(row, column) is not None
            ]
            lines.append("\t".join(cells))
        return "\n".join(lines)

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(self._rows_as_text())
