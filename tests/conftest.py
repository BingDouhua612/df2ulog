"""Shared test configuration.

Real flight logs are **never** committed. Tests marked ``real`` read a local
JSON mapping (path per role) from, in order:

1. ``$DF2ULOG_REAL_LOGS_FILE``;
2. ``tests/real_logs.local.json`` (git-ignored, see
   ``tests/real_logs.example.json``).

If no mapping exists, or the referenced files are missing, real-log tests are
skipped automatically and the synthetic suite still runs everywhere.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _load_real_logs() -> dict[str, Path]:
    candidates: list[Path] = []
    env_file = os.environ.get("DF2ULOG_REAL_LOGS_FILE")
    if env_file:
        candidates.append(Path(env_file))
    candidates.append(Path(__file__).with_name("real_logs.local.json"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                return {
                    str(role): Path(str(path))
                    for role, path in dict(raw).items()
                }
        except (OSError, ValueError, TypeError):
            continue
    return {}


REAL_LOGS: dict[str, Path] = _load_real_logs()
