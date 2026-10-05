"""Shared helpers for GTFS rules: finding collection and polars expressions."""

from __future__ import annotations

import math

import polars as pl

from glacies.validate.gtfs.report import Finding, Severity

EARTH_RADIUS_M = 6_371_008.8
_TIME_RE = r"^(\d{1,3}):([0-5]\d):([0-5]\d)$"


class Collector:
    """Accumulates findings; examples are sorted and capped so reports are deterministic."""

    def __init__(self, max_examples: int) -> None:
        self.max_examples = max_examples
        self._findings: list[Finding] = []

    def add(
        self,
        rule: str,
        severity: Severity,
        file: str | None,
        message: str,
        *,
        examples: pl.Series | list[str] | None = None,
        count: int | None = None,
    ) -> None:
        values: list[str] = []
        if isinstance(examples, pl.Series):
            if count is None:
                count = examples.len()
            values = examples.drop_nulls().cast(pl.String).unique().sort().to_list()
        elif examples is not None:
            values = sorted(set(examples))
            if count is None:
                count = len(examples)
        if count is None or count == 0:
            return
        self._findings.append(
            Finding(
                rule=rule,
                severity=severity,
                file=file,
                message=message,
                count=count,
                examples=values[: self.max_examples],
            )
        )

    @property
    def findings(self) -> list[Finding]:
        return list(self._findings)


def gtfs_seconds(column: str) -> pl.Expr:
    """Parse ``H:MM:SS`` (hours may exceed 24) to seconds; null when absent or malformed."""
    parts = pl.col(column).str.extract_groups(_TIME_RE)
    return (
        parts.struct.field("1").cast(pl.Int64) * 3600
        + parts.struct.field("2").cast(pl.Int64) * 60
        + parts.struct.field("3").cast(pl.Int64)
    )


def to_float(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Float64, strict=False)


def to_int(column: str) -> pl.Expr:
    return pl.col(column).cast(pl.Int64, strict=False)


def haversine_m(lat1: pl.Expr, lon1: pl.Expr, lat2: pl.Expr, lon2: pl.Expr) -> pl.Expr:
    rad = math.pi / 180
    dlat = (lat2 - lat1) * rad
    dlon = (lon2 - lon1) * rad
    a = (dlat / 2).sin() ** 2 + (lat1 * rad).cos() * (lat2 * rad).cos() * (dlon / 2).sin() ** 2
    return 2 * EARTH_RADIUS_M * a.sqrt().arcsin()


def line_numbers(frame: pl.DataFrame, mask: pl.Expr) -> pl.Series:
    """CSV line numbers (header = line 1) of rows matching ``mask``, for examples."""
    return (
        frame.with_row_index("_row")
        .filter(mask)
        .select((pl.lit("line ") + (pl.col("_row") + 2).cast(pl.String)).alias("line"))
        .to_series()
    )
