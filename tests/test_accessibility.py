"""Cumulative accessibility on a 4-zone toy with a hand-made matrix (Phase 3 M3).

Estimated jobs (shares): z0 .1, z1 .2, z2 .3, z3 .4. Population 400/300/200/100 (shares .4/.3/
.2/.1). Median (p50) travel times in minutes; missing pairs are not reached:

    from \\ to   z0   z1   z2   z3
    z0           0   10   25   50
    z1          10    0   40    -
    z2           -    -    0   20
    z3           -    -    -    0

p75 is p50 + 5 min, except z0 -> z3, which is not reached at p75.
"""

from pathlib import Path

import numpy as np
import polars as pl
import pytest

from glacies.analytics.accessibility import (
    build_accessibility,
    cumulative,
    edge_zones,
    opportunities,
    weighted_gini,
    weighted_quantile,
    write_accessibility,
)
from glacies.cities import Accessibility

P50 = {(0, 0): 0, (0, 1): 10, (0, 2): 25, (0, 3): 50, (1, 1): 0, (1, 0): 10, (1, 2): 40}
P50 |= {(2, 2): 0, (2, 3): 20, (3, 3): 0}
SETTINGS = Accessibility(
    percentiles=[50, 75],
    thresholds_min=[15, 30, 45],
    headline_threshold_min=45,
    max_travel_time_min=60,
    edge_buffer_m=1000.0,
)
BBOX = (77.0, 12.0, 77.1, 12.1)


def toy_matrix() -> pl.LazyFrame:
    rows = sorted(P50.items())
    p75 = [None if od == (0, 3) else (m + 5) * 60 for od, m in rows]
    return pl.DataFrame(
        {
            "origin_zone": pl.Series([o for (o, _), _ in rows], dtype=pl.UInt32),
            "dest_zone": pl.Series([d for (_, d), _ in rows], dtype=pl.UInt32),
            "p50_s": pl.Series([m * 60 for _, m in rows], dtype=pl.UInt16),
            "p75_s": pl.Series(p75, dtype=pl.UInt16),
        }
    ).lazy()


def toy_zones() -> pl.DataFrame:
    # z3's point is 0.005 deg (~550 m) from the bbox's east edge: an edge zone.
    return pl.DataFrame(
        {
            "zone_idx": pl.Series([0, 1, 2, 3], dtype=pl.UInt32),
            "h3_cell": ["a", "b", "c", "d"],
            "lat": [12.05, 12.05, 12.05, 12.05],
            "lon": [77.03, 77.04, 77.05, 77.06],
            "pop_lat": [12.05, 12.05, None, 12.05],
            "pop_lon": [77.05, 77.05, None, 77.095],
            "population": [400.0, 300.0, 200.0, 100.0],
        }
    )


def toy_attraction() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "zone_idx": pl.Series([0, 1, 2, 3], dtype=pl.UInt32),
            "employment_score": [0.1, 0.2, 0.3, 0.4],
        }
    )


def shares(table: pl.DataFrame, percentile: int, measure: str) -> list[list[float]]:
    """Rows = zones, columns = thresholds."""
    part = table.filter(pl.col("percentile") == percentile).sort("zone_idx", "threshold_min")
    return [part.filter(pl.col("zone_idx") == z)[f"{measure}_share"].to_list() for z in range(4)]


def test_cumulative_matches_hand_calculation() -> None:
    table = cumulative(toy_matrix(), opportunities(toy_zones(), toy_attraction()), SETTINGS)

    # Jobs within 15/30/45 min at p50: z0 reaches z0+z1 (.3), then z2 (.6), not z3 (50 min).
    np.testing.assert_allclose(
        shares(table, 50, "est_jobs"),
        [[0.3, 0.6, 0.6], [0.3, 0.3, 0.6], [0.3, 0.7, 0.7], [0.4, 0.4, 0.4]],
    )
    np.testing.assert_allclose(
        shares(table, 50, "population"),
        [[0.7, 0.9, 0.9], [0.7, 0.7, 0.9], [0.2, 0.3, 0.3], [0.1, 0.1, 0.1]],
    )
    # p75 (+5 min): z1 -> z2 takes 45 min, which is within 45 (<=), z0 -> z2 is 30 min.
    np.testing.assert_allclose(
        shares(table, 75, "est_jobs"),
        [[0.3, 0.6, 0.6], [0.3, 0.3, 0.6], [0.3, 0.7, 0.7], [0.4, 0.4, 0.4]],
    )


def test_threshold_is_inclusive_and_unreached_is_excluded() -> None:
    settings = SETTINGS.model_copy(update={"thresholds_min": [10, 20, 25]})
    table = cumulative(toy_matrix(), opportunities(toy_zones(), toy_attraction()), settings)

    # p50 exactly 10 / 20 / 25 min counts; p75 of z0 -> z3 is null and never counts.
    assert shares(table, 50, "est_jobs")[0] == pytest.approx([0.3, 0.3, 0.6])
    assert shares(table, 50, "est_jobs")[2] == pytest.approx([0.3, 0.7, 0.7])
    assert shares(table, 75, "est_jobs")[0] == pytest.approx([0.1, 0.3, 0.3])


def test_weighted_statistics_match_hand_calculation() -> None:
    # Headline values (p50, 45 min) .6/.6/.7/.4, weighted by population shares .4/.3/.2/.1.
    values, weights = np.array([0.6, 0.6, 0.7, 0.4]), np.array([0.4, 0.3, 0.2, 0.1])

    # Sorted: .4 (cum .1), .6 (.5), .6 (.8), .7 (1.0).
    assert weighted_quantile(values, weights, 0.10) == pytest.approx(0.4)
    assert weighted_quantile(values, weights, 0.50) == pytest.approx(0.6)
    assert weighted_quantile(values, weights, 0.90) == pytest.approx(0.7)
    # Pairs: (.4,.6) .1*.7*.2 + (.4,.7) .1*.2*.3 + (.6,.7) .7*.2*.1 = .034, both orders .068;
    # Gini = .068 / (2 * 1 * mean .6).
    assert weighted_gini(values, weights) == pytest.approx(0.068 / 1.2)
    assert weighted_gini(np.array([0.5, 0.5]), np.array([1.0, 3.0])) == 0.0


def test_edge_zones() -> None:
    lat = np.array([12.05, 12.05, 12.001])
    lon = np.array([77.05, 77.095, 77.05])

    assert edge_zones(lat, lon, BBOX, 1000.0).tolist() == [False, True, True]


def test_build_headline_summary_and_outputs(tmp_path: Path) -> None:
    build = build_accessibility(
        toy_zones(), toy_attraction(), toy_matrix(), SETTINGS, bbox=BBOX, index_total=1000
    )

    assert build.headline == pytest.approx(0.4 * 0.6 + 0.3 * 0.6 + 0.2 * 0.7 + 0.1 * 0.4)  # .60
    assert build.edge_count == 1  # z3's population point is near the east edge
    inner = build.summary.filter(
        (pl.col("scope") == "excluding edge zones")
        & (pl.col("percentile") == 50)
        & (pl.col("threshold_min") == 45)
        & (pl.col("measure") == "est_jobs")
    )
    assert inner["population_weighted_mean"][0] == pytest.approx((0.24 + 0.18 + 0.14) / 0.9)
    row = build.zones.filter((pl.col("zone_idx") == 2) & (pl.col("threshold_min") == 30))
    assert row.filter(pl.col("percentile") == 50)["est_opportunity_index"][0] == pytest.approx(700)

    hashes = []
    for run in ("a", "b"):
        manifest = write_accessibility(
            build, tmp_path / run, city="toy", scenario="baseline", settings=SETTINGS,
            index_total=1000, inputs=[],
        )  # fmt: skip
        hashes.append(manifest.outputs)
    assert hashes[0] == hashes[1]
    text = (tmp_path / "a" / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "**60.0% of the city's estimated jobs** within 45 min" in text
    assert "not a count of jobs" in text


def test_missing_attraction_is_reported() -> None:
    partial = toy_attraction().head(3)
    with pytest.raises(ValueError, match="every zone"):
        opportunities(toy_zones(), partial)


def test_headline_must_be_a_configured_threshold() -> None:
    with pytest.raises(ValueError, match="headline_threshold_min"):
        Accessibility(thresholds_min=[15, 30], headline_threshold_min=45)


def test_headline_sensitivity_matches_hand_calculation(tmp_path: Path) -> None:
    alternatives = {"baseline": np.array([0.1, 0.2, 0.3, 0.4]), "flat": np.full(4, 0.25)}

    build = build_accessibility(
        toy_zones(), toy_attraction(), toy_matrix(), SETTINGS, bbox=BBOX, index_total=1000,
        alternatives=alternatives,
    )  # fmt: skip

    table = build.sensitivity
    assert table is not None
    means = {
        (w, t): v
        for w, t, v in table.select(
            "weighting", "threshold_min", "population_weighted_mean"
        ).iter_rows()
    }
    # Baseline equals the headline path: .31 / .51 / .60 at 15 / 30 / 45 min.
    assert [means[("baseline", t)] for t in (15, 30, 45)] == pytest.approx([0.31, 0.51, 0.60])
    assert means[("baseline", 45)] == pytest.approx(build.headline)
    # Flat jobs (.25 per zone): zones reached 2/2/1/1, 3/2/2/1, 3/3/2/1 at 15/30/45 min.
    assert [means[("flat", t)] for t in (15, 30, 45)] == pytest.approx([0.425, 0.575, 0.65])
    # Population as a reference: reach .9/.9/.3/.1 at 45 min, weighted .4/.3/.2/.1.
    assert means[("population (reference, not a proxy)", 45)] == pytest.approx(0.70)
    change = table.filter((pl.col("weighting") == "flat") & (pl.col("threshold_min") == 45))
    assert change["change_vs_baseline"][0] == pytest.approx(0.05)

    manifest = write_accessibility(
        build, tmp_path / "out", city="toy", scenario="baseline", settings=SETTINGS,
        index_total=1000, inputs=[],
    )  # fmt: skip
    assert manifest.headline_by_weighting["flat"] == pytest.approx(0.65)
    text = (tmp_path / "out" / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "| flat | 42.5% | 57.5% | 65.0% | +5.00 pp |" in text
