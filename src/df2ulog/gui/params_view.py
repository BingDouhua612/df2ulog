"""Parameter-change table widget + dialog for the GUI (all PARM records)."""

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
    QWidget,
)

from .i18n import LANG_ZH, normalize_lang, tr

ParamEntry = tuple[str, float, int]  # name, value, time_us


class ParamTableView(QWidget):
    """Reusable table with search, row count and copy-to-clipboard."""

    def __init__(self, parent: QWidget | None = None, lang: str = LANG_ZH) -> None:
        super().__init__(parent)
        self._lang = normalize_lang(lang)
        self._entries: list[ParamEntry] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(self._t("params.search"))
        self.search_edit.textChanged.connect(self._apply_filter)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Hint")
        top.addWidget(self.search_edit, stretch=1)
        top.addWidget(self.count_label)
        layout.addLayout(top)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(self._headers())
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.copy_button = QPushButton(self._t("params.copy"))
        self.copy_button.clicked.connect(self._copy_all)
        bottom.addWidget(self.copy_button)
        layout.addLayout(bottom)
        self._populate()

    # ------------------------------------------------------------------ i18n
    def _t(self, key: str, **kwargs: object) -> str:
        return tr(key, self._lang, **kwargs)

    def _headers(self) -> list[str]:
        return [
            self._t("params.col.index"),
            self._t("params.col.name"),
            self._t("params.col.value"),
            self._t("params.col.time"),
        ]

    def set_language(self, lang: str) -> None:
        self._lang = normalize_lang(lang)
        self.table.setHorizontalHeaderLabels(self._headers())
        self.search_edit.setPlaceholderText(self._t("params.search"))
        self.copy_button.setText(self._t("params.copy"))
        self._populate()

    # ----------------------------------------------------------------- table
    def set_entries(self, entries: Sequence[ParamEntry]) -> None:
        self._entries = list(entries)
        self._populate()

    def _populate(self) -> None:
        self.table.setRowCount(0)
        self.table.setRowCount(len(self._entries))
        for row, (name, value, time_us) in enumerate(self._entries):
            cells = (
                str(row + 1),
                name,
                str(value),
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
        names = len({entry[0] for entry in self._entries})
        if self._entries:
            self.count_label.setText(
                self._t("params.count", records=len(self._entries), names=names)
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

    def rows_as_text(self) -> str:
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
        QApplication.clipboard().setText(self.rows_as_text())


class ParamTableDialog(QDialog):
    """Dialog wrapper around :class:`ParamTableView` (batch: file selector)."""

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

        if len(self._files) > 1:
            self.file_combo = QComboBox()
            for label, _entries in self._files:
                self.file_combo.addItem(label)
            self.file_combo.currentIndexChanged.connect(self._populate)
            root.addWidget(self.file_combo)
        else:
            self.file_combo = QComboBox()
            if self._files:
                self.file_combo.addItem(self._files[0][0])

        self.view = ParamTableView(self, self._lang)
        self.table = self.view.table
        self.search_edit = self.view.search_edit
        self.count_label = self.view.count_label
        root.addWidget(self.view, stretch=1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.close_button = QPushButton(self._t("params.close"))
        self.close_button.clicked.connect(self.accept)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)
        self._populate()

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(key, self._lang, **kwargs)

    def _populate(self) -> None:
        if not self._files:
            self.view.set_entries([])
            return
        index = max(0, self.file_combo.currentIndex())
        self.view.set_entries(self._files[index][1])

    def _copy_all(self) -> None:
        self.view._copy_all()
