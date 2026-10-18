import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from fixtures.make_fixtures import make_minimal_fixture
from PySide6.QtWidgets import QApplication

from df2ulog.converter import ConversionOptions, convert_file
from df2ulog.gui.app import MainWindow
from df2ulog.gui.backend import (
    BatchItemResult,
    BatchOutcome,
    ConversionOutcome,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_window_constructs(qapp):
    window = MainWindow()
    assert "df2ulog" in window.windowTitle()
    assert not window.convert_button.isEnabled()
    window.close()


def test_set_source_updates_summary(qapp, tmp_path):
    fx = make_minimal_fixture(tmp_path)
    window = MainWindow()
    window.set_source(fx.bin_path)
    assert "minimal.bin" in window.source_label.text()
    assert "binary" in window.source_label.text()
    assert window.convert_button.isEnabled()
    window.close()


def test_apply_progress_and_outcome(qapp, tmp_path):
    fx = make_minimal_fixture(tmp_path)
    out = tmp_path / "minimal.ulg"
    result = convert_file(fx.bin_path, ConversionOptions(output=out))
    window = MainWindow()
    window.set_source(fx.bin_path)
    window._apply_progress("write", 55)
    assert window.progress_bar.value() == 55
    window._apply_outcome(
        ConversionOutcome(ok=True, message="转换完成", output_path=out, result=result)
    )
    text = window.result_text.toPlainText()
    assert "topic" in text.lower()
    assert "记录" in text
    assert window.open_folder_button.isEnabled()
    window.close()


def test_apply_error_outcome(qapp, tmp_path):
    window = MainWindow()
    window.set_source(make_minimal_fixture(tmp_path).bin_path)
    window._apply_outcome(
        ConversionOutcome(ok=False, message="输出文件已存在", error_code=6)
    )
    assert "输出文件已存在" in window.status_label.text()
    assert not window.open_folder_button.isEnabled()
    window.close()


def test_theme_applied(qapp):
    from df2ulog.gui.theme import apply_theme

    apply_theme(qapp)
    assert "QFrame#DropZone" in qapp.styleSheet()
    assert "QPushButton#Primary" in qapp.styleSheet()
    assert qapp.palette().window().color().name() == "#12161c"


def test_output_preview_updates(qapp, tmp_path):
    fx = make_minimal_fixture(tmp_path)
    window = MainWindow()
    window.set_source(fx.bin_path)
    out_dir = tmp_path / "outdir"
    window.output_dir_edit.setText(str(out_dir))
    window._update_output_preview()
    text = window.output_preview_label.text()
    assert "minimal.ulg" in text
    assert str(out_dir) in text
    window.close()


def test_drag_highlight_toggle(qapp):
    window = MainWindow()
    window._set_drag_active(True)
    assert window.drop_zone.property("dragging") is True
    window._set_drag_active(False)
    assert not window.drop_zone.property("dragging")
    window.close()


def test_add_sources_populates_queue(qapp, tmp_path):
    fx = make_minimal_fixture(tmp_path)
    window = MainWindow()
    window.add_sources([fx.bin_path, fx.log_path])
    assert window.queue_table.rowCount() == 2
    assert "2 个文件" in window.source_label.text()
    assert window.convert_button.isEnabled()
    window.close()


def test_apply_batch_outcome_updates_rows(qapp, tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    fx = make_minimal_fixture(first_dir)
    fx2 = make_minimal_fixture(second_dir)
    ok_output = tmp_path / "ok.ulg"
    ok_output.write_bytes(b"x")
    window = MainWindow()
    window.add_sources([fx.bin_path, fx.log_path, fx2.bin_path])
    outcome = BatchOutcome(
        items=(
            BatchItemResult(
                source=fx.bin_path, status="success", message="ok", output_path=ok_output
            ),
            BatchItemResult(source=fx.log_path, status="skipped", message="输出已存在"),
            BatchItemResult(source=fx2.bin_path, status="failed", message="bad", error_code=4),
        )
    )
    window._apply_batch_outcome(outcome)
    statuses = [
        window.queue_table.item(row, 3).text() for row in range(3)
    ]
    assert statuses == ["成功", "跳过", "失败"]
    text = " ".join(window.result_text.toPlainText().split())
    assert "成功 1" in text
    assert "跳过 1" in text
    assert "失败 1" in text
    assert window.open_folder_button.isEnabled()
    window.close()


def test_cancel_request_sets_event(qapp, tmp_path):
    fx = make_minimal_fixture(tmp_path)
    window = MainWindow()
    window.add_sources([fx.bin_path])
    window._busy = True
    window._cancel_event = threading.Event()
    window.cancel_button.setEnabled(True)
    window._cancel_batch()
    assert window._cancel_event.is_set()
    assert "取消" in window.status_label.text()
    window.close()


def test_batch_start_threads_and_finishes(qapp, tmp_path, monkeypatch):
    fx = make_minimal_fixture(tmp_path)
    window = MainWindow()
    window.add_sources([fx.bin_path, fx.log_path])

    def fake_run_batch(request, progress=None, on_item=None, should_cancel=None):
        items = []
        total = len(request.sources)
        for index, source in enumerate(request.sources):
            if progress is not None:
                progress(index, total, "write", 50)
            item = BatchItemResult(
                source=source,
                status="success",
                message="ok",
                output_path=tmp_path / f"{source.stem}.ulg",
            )
            items.append(item)
            if on_item is not None:
                on_item(index, item)
        return BatchOutcome(items=tuple(items))

    monkeypatch.setattr("df2ulog.gui.app.run_batch", fake_run_batch)
    window.start_conversion()
    app = QApplication.instance()
    deadline = time.time() + 10
    while window._busy and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert not window._busy
    assert window.queue_table.rowCount() == 2
    summary = window.result_text.toPlainText() + window.status_label.text()
    assert "成功" in summary
    window.close()


def test_app_icon_loaded(qapp):
    from df2ulog.gui.widgets import app_icon

    icon = app_icon()
    assert not icon.isNull()
    assert icon.availableSizes()
