"""Markdown build report of an all-or-nothing assignment (Phase 6 M1-M2)."""

from __future__ import annotations

import polars as pl

from glacies.assignment.writer import AssignmentManifest

TOP_SEGMENTS = 15
TOP_ROUTES = 10
SET_NAMES = {
    "training": "Training stations",
    "held_out": "Held-out stations",
    "excluded": "Excluded lines",
}


def _clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def _msa_lines(m: AssignmentManifest, convergence: pl.DataFrame | None) -> list[str]:
    if m.msa is None or convergence is None:
        return []
    x = m.msa
    lines = [
        "## Crowding loop",
        "",
        f"Logit scale {x.theta_per_min:g} per generalised minute; fares "
        f"{'included' if x.use_fares else 'left out'}. {x.pairs:,} pairs, {x.alternatives:,} "
        f"alternatives ({x.alternatives / x.pairs:.2f} per pair), {x.rides:,} rides stored. "
        f"{'Converged' if x.converged else 'Did not converge'} after {x.iterations} iterations "
        f"(final gap {x.final_gap:.4f}).",
        "",
        "| Iteration | Gap | Mean cost (min) | Highest multiplier |",
        "|---:|---:|---:|---:|",
    ]
    last = convergence["iteration"].max()
    for row in convergence.iter_rows(named=True):
        n = row["iteration"]
        if n <= 5 or n % 5 == 0 or n == last:
            gap = "-" if row["gap"] != row["gap"] else f"{row['gap']:.4f}"
            lines.append(
                f"| {n} | {gap} | {row['mean_cost_min']:.1f} | {row['max_multiplier']:.2f} |"
            )
    return [*lines, ""]


def build_report(
    m: AssignmentManifest,
    loads: pl.DataFrame,
    routes: pl.DataFrame,
    trips: pl.DataFrame,
    stop_names: pl.DataFrame,
    report_window: tuple[int, int],
    route_table: pl.DataFrame,
    convergence: pl.DataFrame | None = None,
) -> str:
    """``routes``: route_idx, mode, short_name; ``trips``: trip_idx, route_idx;
    ``stop_names``: stop_idx, name (parent station names for platforms); ``route_table``:
    the per-route metrics written to routes.parquet."""
    s, c = m.stats, m.metrics
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
        *_msa_lines(m, convergence),
        "## City summary (PRD §31)",
        "",
        "Per transit trip, door to door; crowding is the share of passenger-km above design "
        "capacity among vehicles leaving a stop in the report window.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| travel time | {c.mean_travel_min:.1f} min |",
        f"| ... in vehicles | {c.mean_in_vehicle_min:.1f} min |",
        f"| ... waiting | {c.mean_waiting_min:.1f} min |",
        f"| ... walking | {c.mean_walking_min:.1f} min |",
        f"| ... riding to a station | {c.mean_riding_min:.1f} min |",
        f"| transfers | {c.transfers_per_trip:.2f} |",
        f"| trips starting with a ride to a station | {c.share_riding_to_station:.1%} |",
        f"| passenger-km (straight line) | {c.passenger_km:,.0f} |",
        f"| crowding (above design capacity) | {c.peak_crowded_pkm_share:.1%} |",
        f"| above crush capacity | {c.peak_crush_pkm_share:.1%} |",
        f"| metro gate entries | {c.metro_entries:,.0f} |",
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
    if m.station_fits:
        lines += [
            "",
            "## Metro gate entries against BMRCL (validation level 4)",
            "",
            "Shares of each set's entries, as demand calibration scores them; simulated entries "
            "are trips leaving home 08:00-10:00, observed ones tap-ins in hours 8-9.",
            "",
            "| Set | Stations | R² (share) | r | Mean GEH | Simulated / observed |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for name, f in m.station_fits.items():
            lines.append(
                f"| {SET_NAMES.get(name, name)} | {f.items} | {f.r2_share:.2f} "
                f"| {f.correlation:.2f} | {f.mean_geh:.1f} | {f.level_ratio:.2f} |"
            )
    lines += [
        "",
        f"## {TOP_ROUTES} routes with the most passenger-km",
        "",
        "| Mode | Route | Boardings | Passenger-km | Peak utilisation | Peak max load factor |",
        "|---|---|---:|---:|---:|---:|",
    ]
    busiest = route_table.sort("passenger_km", "route_idx", descending=[True, False]).head(
        TOP_ROUTES
    )
    for row in busiest.iter_rows(named=True):
        utilisation = row["peak_utilisation"]
        top_lf = row["peak_max_load_factor"]
        lines.append(
            f"| {row['mode']} | {row['short_name']} | {row['boardings']:,.0f} "
            f"| {row['passenger_km']:,.0f} "
            f"| {'-' if utilisation is None else f'{utilisation:.2f}'} "
            f"| {'-' if top_lf is None else f'{top_lf:.2f}'} |"
        )
    lines += [
        "",
        "All flows are Simulated (Estimated demand on the scheduled timetable); capacities are "
        "Assumed (`assignment.toml`). Routes missing from the bus feed push their riders onto "
        "other routes, so heavy bus loads can be artefacts of feed coverage.",
        "",
    ]
    return "\n".join(lines)
