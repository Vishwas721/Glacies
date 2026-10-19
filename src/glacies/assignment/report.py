"""Markdown build report of an all-or-nothing assignment (Phase 6 M1)."""

from __future__ import annotations

import polars as pl

from glacies.assignment.aon import AssignmentManifest

TOP_SEGMENTS = 15


def _clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def build_report(
    m: AssignmentManifest,
    loads: pl.DataFrame,
    routes: pl.DataFrame,
    trips: pl.DataFrame,
    stop_names: pl.DataFrame,
    report_window: tuple[int, int],
) -> str:
    """``routes``: route_idx, mode, short_name; ``trips``: trip_idx, route_idx;
    ``stop_names``: stop_idx, name (parent station names for platforms)."""
    s = m.stats
    start, end = report_window
    named = loads.join(trips.select("trip_idx", "route_idx"), on="trip_idx").join(
        routes.select("route_idx", "mode", "short_name"), on="route_idx"
    )
    peak = named.filter((pl.col("departure") >= start) & (pl.col("departure") < end))
    lines = [
        f"# Assignment — `{m.city}` / `{m.scenario}` (Simulated)",
        "",
        f"Builder {m.builder_version} · {m.method} · departures {m.window} "
        f"({m.departures}) · crowding reported for vehicles leaving a stop {m.report_window}",
        "",
        "| Quantity | Value |",
        "|---|---:|",
        f"| OD trips (Estimated) | {s.trips:,.0f} |",
        f"| on transit | {s.trips_transit:,.0f} ({s.trips_transit / s.trips:.1%}) |"
        if s.trips
        else "| on transit | 0 |",
        f"| walking all the way is as fast | {s.trips_walked:,.0f} |",
        f"| not reached in the window | {s.trips_unreached:,.0f} |",
        f"| boardings | {s.boardings:,.0f} |",
        f"| transfers per transit trip | {s.transfers_per_transit_trip:.2f} |",
        f"| passenger-hours in vehicles | {s.passenger_hours:,.0f} |",
        f"| segments in the report window | {s.peak_segments:,} |",
        f"| ... above design capacity | {s.peak_segments_over_capacity:,} |",
        f"| ... above crush capacity | {s.peak_segments_over_crush:,} |",
        "",
        "Demand outside the window is not modelled, so vehicles before about 08:30 and after "
        "10:00 carry too few people; the report window avoids most of that edge.",
        "",
        "## Peak load by line or mode (report window)",
        "",
        "| Mode | Line | Segments | Mean load | Max load | Max load factor | Above capacity |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    by_line = (
        peak.with_columns(
            pl.when(pl.col("mode") == "bus")
            .then(pl.lit("(all buses)"))
            .otherwise(pl.col("short_name"))
            .alias("line")
        )
        .group_by("mode", "line")
        .agg(
            pl.len().alias("segments"),
            pl.col("load").mean().alias("mean"),
            pl.col("load").max().alias("max"),
            pl.col("load_factor").max().alias("max_lf"),
            (pl.col("load_factor") > 1).sum().alias("over"),
        )
        .sort("mode", "line")
    )
    for mode, line, segments, mean, top, max_lf, over in by_line.iter_rows():
        lines.append(
            f"| {mode} | {line} | {segments:,} | {mean:,.0f} | {top:,.0f} "
            f"| {max_lf:.2f} | {over:,} |"
        )
    lines += [
        "",
        f"## {TOP_SEGMENTS} busiest segments by load factor (report window)",
        "",
        "| Route | From | To | Leaves | Load | Capacity | Load factor |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    names = stop_names.select("stop_idx", "name")
    top = (
        peak.sort("load_factor", "trip_idx", "position", descending=[True, False, False])
        .head(TOP_SEGMENTS)
        .join(names.rename({"stop_idx": "from_stop_idx", "name": "from"}), on="from_stop_idx")
        .join(names.rename({"stop_idx": "to_stop_idx", "name": "to"}), on="to_stop_idx")
        .sort("load_factor", "trip_idx", "position", descending=[True, False, False])
    )
    for row in top.iter_rows(named=True):
        lines.append(
            f"| {row['short_name']} | {row['from']} | {row['to']} | {_clock(row['departure'])} "
            f"| {row['load']:,.0f} | {row['capacity']:,} | {row['load_factor']:.2f} |"
        )
    # The last stop of a trip has no segment row, but nobody boards there.
    boardings = (
        named.with_columns(
            pl.when(pl.col("mode") == "bus")
            .then(pl.lit("(all buses)"))
            .otherwise(pl.col("short_name"))
            .alias("line")
        )
        .group_by("mode", "line")
        .agg(pl.col("boardings").sum())
        .sort("mode", "line")
    )
    lines += [
        "",
        "## Boardings by line (whole window)",
        "",
        "Metro boardings count line changes inside a station again, so they exceed gate entries.",
        "",
        "| Mode | Line | Boardings |",
        "|---|---|---:|",
    ]
    for mode, line, total in boardings.iter_rows():
        lines.append(f"| {mode} | {line} | {total:,.0f} |")
    lines += [
        "",
        "All flows are Simulated (Estimated demand on the scheduled timetable); capacities are "
        "Assumed (`assignment.toml`). Routes missing from the bus feed push their riders onto "
        "other routes, so heavy bus loads can be artefacts of feed coverage.",
        "",
    ]
    return "\n".join(lines)
