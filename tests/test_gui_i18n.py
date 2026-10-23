import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from df2ulog.gui.app import MainWindow, gui_settings
from df2ulog.gui.i18n import LANG_EN, LANG_ZH, STRINGS, tr


@pytest.fixture(autouse=True)
def _reset_language():
    settings = gui_settings()
    settings.setValue("language", LANG_ZH)
    settings.sync()
    yield
    settings.setValue("language", LANG_ZH)
    settings.sync()


def test_i18n_has_all_translations():
    assert set(STRINGS[LANG_ZH]) == set(STRINGS[LANG_EN]), (
        set(STRINGS[LANG_ZH]) ^ set(STRINGS[LANG_EN])
    )


def test_tr_translates_and_falls_back():
    assert tr("row.success", LANG_EN) == "Success"
    assert tr("row.success", LANG_ZH) == "成功"
    assert tr("missing.key", LANG_EN) == "missing.key"


def test_language_toggle_updates_ui(qapp):
    window = MainWindow()
    assert window.convert_button.text() == "开始批量转换"
    assert window.lang_button.text() == "EN"

    window._toggle_language()
    assert window.lang_button.text() == "中文"
    assert window.convert_button.text() == "Start batch conversion"
    assert window.source_label.text() == "No file selected"
    assert window.queue_table.horizontalHeaderItem(0).text() == "File"
    assert "batch converter" in window.windowTitle()

    window._toggle_language()
    assert window.lang_button.text() == "EN"
    assert window.convert_button.text() == "开始批量转换"
    assert window.queue_table.horizontalHeaderItem(0).text() == "文件"
    window.close()


def test_language_persisted(qapp):
    window = MainWindow()
    window._toggle_language()
    window.close()

    settings = gui_settings()
    assert settings.value("language") == LANG_EN

    window2 = MainWindow()
    assert window2.lang_button.text() == "中文"
    assert window2.convert_button.text() == "Start batch conversion"
    window2.close()
