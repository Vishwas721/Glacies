"""Filesystem helpers shared by pipeline stages."""

from __future__ import annotations

import time
from pathlib import Path

# On Windows, antivirus or the search indexer can hold a freshly written large file open for a
# few seconds, making a directory rename fail with "Access is denied".
RENAME_ATTEMPTS = 10
RENAME_DELAY_SECONDS = 1.0


def rename_with_retry(source: Path, target: Path) -> None:
    """Rename ``source`` to ``target``, retrying while a transient file lock is held."""
    for attempt in range(1, RENAME_ATTEMPTS + 1):
        try:
            source.rename(target)
            return
        except PermissionError:
            if attempt == RENAME_ATTEMPTS:
                raise
            time.sleep(RENAME_DELAY_SECONDS)
