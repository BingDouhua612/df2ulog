
from fixtures.make_fixtures import make_minimal_fixture

from df2ulog.gui.backend import BatchRequest, run_batch


def _make_two(tmp_path):
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = make_minimal_fixture(first_dir)
    second = make_minimal_fixture(second_dir)
    return first, second


def test_run_batch_success(tmp_path):
    first, second = _make_two(tmp_path)
    second_bin = second.bin_path.rename(second.bin_path.with_name("second.BIN"))
    out_dir = tmp_path / "out"
    progress = []
    items = []
    outcome = run_batch(
        BatchRequest(
            sources=(first.bin_path, second_bin),
            output_dir=out_dir,
        ),
        progress=lambda idx, total, phase, pct: progress.append((idx, total, phase, pct)),
        on_item=lambda idx, item: items.append((idx, item)),
    )
    assert outcome.ok
    assert not outcome.cancelled
    assert [item.status for item in outcome.items] == ["success", "success"]
    assert outcome.success_count == 2
    assert outcome.failed_count == 0
    assert outcome.skipped_count == 0
    assert all(item.output_path and item.output_path.exists() for item in outcome.items)
    assert [entry[0] for entry in items] == [0, 1]
    assert progress[0][0] == 0 and progress[0][1] == 2
    assert {entry[2] for entry in progress} >= {"scan", "done"}
    assert (out_dir / "minimal.ulg").exists()
    assert (out_dir / "second.ulg").exists()


def test_run_batch_skips_existing_without_overwrite(tmp_path):
    first, _second = _make_two(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / "minimal.ulg"
    existing.write_bytes(b"keep-me")
    outcome = run_batch(
        BatchRequest(sources=(first.bin_path,), output_dir=out_dir)
    )
    assert outcome.ok
    assert outcome.items[0].status == "skipped"
    assert outcome.skipped_count == 1
    assert existing.read_bytes() == b"keep-me"


def test_run_batch_overwrite(tmp_path):
    first, _second = _make_two(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / "minimal.ulg"
    existing.write_bytes(b"old")
    outcome = run_batch(
        BatchRequest(sources=(first.bin_path,), output_dir=out_dir, overwrite=True)
    )
    assert outcome.ok
    assert outcome.items[0].status == "success"
    assert existing.read_bytes()[:7] == b"ULog\x01\x12\x35"


def test_run_batch_continues_after_failure(tmp_path):
    first, _second = _make_two(tmp_path)
    bad = tmp_path / "bad.BIN"
    bad.write_bytes(b"this is not a DataFlash log")
    outcome = run_batch(
        BatchRequest(sources=(first.bin_path, bad), output_dir=tmp_path / "out")
    )
    assert [item.status for item in outcome.items] == ["success", "failed"]
    assert outcome.success_count == 1
    assert outcome.failed_count == 1
    assert not outcome.ok
    assert outcome.items[1].error_code == 3


def test_run_batch_cancel_stops_remaining(tmp_path):
    first, second = _make_two(tmp_path)
    calls = []

    def should_cancel() -> bool:
        calls.append(1)
        return len(calls) > 1  # cancel before the second file

    outcome = run_batch(
        BatchRequest(
            sources=(first.bin_path, second.bin_path, first.bin_path),
            output_dir=tmp_path / "out",
        ),
        should_cancel=should_cancel,
    )
    assert outcome.cancelled
    assert outcome.items[0].status == "success"
    assert outcome.items[1].status == "cancelled"
    assert outcome.items[2].status == "cancelled"


def test_run_batch_empty(tmp_path):
    outcome = run_batch(BatchRequest(sources=()))
    assert outcome.items == ()
    assert outcome.ok
    assert not outcome.cancelled


def test_run_batch_verify_option(tmp_path):
    first, _second = _make_two(tmp_path)
    outcome = run_batch(
        BatchRequest(
            sources=(first.bin_path,),
            output_dir=tmp_path / "out",
            verify=True,
        )
    )
    assert outcome.ok
    assert outcome.items[0].verify_ok is True
    assert outcome.items[0].elapsed_s >= 0
