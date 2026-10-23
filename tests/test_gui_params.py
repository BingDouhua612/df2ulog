import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from fixtures.make_fixtures import make_minimal_fixture
from PySide6.QtWidgets import QApplication

from df2ulog.converter import ConversionOptions, convert_file
from df2ulog.gui.app import MainWindow
from df2ulog.gui.backend import ConversionOutcome
from df2ulog.gui.i18n import LANG_EN, LANG_ZH
from df2ulog.gui.params_view import ParamTableDialog


def test_param_dialog_table_and_filter(qapp):
    entries = [
        ("PSC_POSXY_P", 1.0, 1_000_000),
        ("PSC_VELXY_P", 2.0, 2_000_000),
        ("PSC_VELXY_P", 2.5, 3_000_000),
    ]
    dialog = ParamTableDialog(None, [("flight.BIN", entries)], lang=LANG_ZH)
    assert dialog.table.rowCount() == 3
    assert dialog.count_label.text().startswith("3 条记录")
    assert dialog.table.item(1, 1).text() == "PSC_VELXY_P"

    dialog.search_edit.setText("VELXY")
    QApplication.instance().processEvents()
    visible = [row for row in range(3) if not dialog.table.isRowHidden(row)]
    assert visible == [1, 2]

    dialog.search_edit.setText("2.5")
    QApplication.instance().processEvents()
    visible = [row for row in range(3) if not dialog.table.isRowHidden(row)]
    assert visible == [2]

    dialog._copy_all()
    assert "PSC_VELXY_P" in QApplication.clipboard().text()
    dialog.close()


def test_param_dialog_english(qapp):
    dialog = ParamTableDialog(None, [("flight.BIN", [("P", 1.0, 1)])], lang=LANG_EN)
    assert dialog.windowTitle() == "Parameter table"
    assert dialog.table.horizontalHeaderItem(1).text() == "Parameter"
    dialog.close()


def test_params_button_enabled_after_conversion(qapp, tmp_path):
    fx = make_minimal_fixture(tmp_path)
    output = tmp_path / "out.ulg"
    result = convert_file(fx.bin_path, ConversionOptions(output=output))

    window = MainWindow()
    window.set_source(fx.bin_path)
    assert not window.params_button.isEnabled()
    window._apply_outcome(
        ConversionOutcome(ok=True, message="ok", output_path=output, result=result)
    )
    assert window.params_button.isEnabled()
    window.close()
