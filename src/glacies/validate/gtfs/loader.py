"""Load a GTFS directory as all-text polars tables.

Every column is read as a string, so malformed values become findings instead of parse errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import polars as pl


@dataclass(frozen=True)
class Feed:
    tables: dict[str, pl.DataFrame]
    unreadable: dict[str, str] = field(default_factory=dict)  # file stem -> error message

    def has(self, name: str) -> bool:
        return name in self.tables

    def has_columns(self, name: str, *columns: str) -> bool:
        return name in self.tables and all(c in self.tables[name].columns for c in columns)

    def __getitem__(self, name: str) -> pl.DataFrame:
        return self.tables[name]


def load_feed(directory: Path) -> Feed:
    tables: dict[str, pl.DataFrame] = {}
    unreadable: dict[str, str] = {}
    for path in sorted(directory.glob("*.txt")):
        try:
            frame = pl.read_csv(path, infer_schema=False, encoding="utf8-lossy")
        except (pl.exceptions.PolarsError, OSError) as exc:
            unreadable[path.stem] = str(exc).splitlines()[0]
            continue
        frame = frame.rename({c: c.lstrip("﻿").strip() for c in frame.columns})
        # Trim whitespace and turn empty strings into nulls, the GTFS meaning of "absent".
        frame = frame.with_columns(pl.col(pl.String).str.strip_chars().replace("", None))
        tables[path.stem] = frame
    return Feed(tables=tables, unreadable=unreadable)
