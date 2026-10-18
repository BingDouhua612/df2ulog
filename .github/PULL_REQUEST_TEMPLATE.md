## Summary

<!-- What does this PR change and why? -->

## Verification

<!-- Commands you ran and their result. -->

- [ ] `ruff check src tests`
- [ ] `pytest -q -m "not real"`
- [ ] GUI tests (if GUI changed): `QT_QPA_PLATFORM=offscreen pytest tests/test_gui_app.py tests/test_gui_batch.py -q`

## Related issues

<!-- Fixes #... -->

## Checklist

- [ ] No real flight logs, personal paths or private data added to the repo.
- [ ] Output determinism preserved (same input + options → byte-identical `.ulg`).
- [ ] Docs/changelog updated when behavior or options changed.
