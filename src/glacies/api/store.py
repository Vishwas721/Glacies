"""Read-only DuckDB queries over the canonical Parquet outputs (PRD §49).

Each query opens its own in-memory connection: connections are cheap, and FastAPI runs sync
endpoints on a thread pool where a shared connection would need a lock. Paths always come from
the city configuration, never from the request, and are passed as parameters, not spliced in.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any, TypeVar

import duckdb
import polars as pl

T = TypeVar("T")


def query(sql: str, params: dict[str, Any] | None = None) -> pl.DataFrame:
    with duckdb.connect() as con:
        return con.execute(sql, params or {}).pl()


class Memo:
    """Results that depend only on some files, recomputed when any of them changes.

    The network tables change only when a build replaces them, and assembling them (joins
    over 1.5M stop times) takes long enough to be worth keeping between requests.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._values: dict[tuple[object, ...], object] = {}

    def get(self, key: tuple[object, ...], files: list[Path], compute: Callable[[], T]) -> T:
        stamp = (*key, *((str(f), f.stat().st_mtime_ns) for f in files))
        with self._lock:
            if stamp in self._values:
                return self._values[stamp]  # type: ignore[return-value]
        value = compute()
        with self._lock:
            # Drop older versions of the same key so a rebuild does not keep both in memory.
            for old in [k for k in self._values if k[: len(key)] == key]:
                del self._values[old]
            self._values[stamp] = value
        return value
