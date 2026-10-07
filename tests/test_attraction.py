"""Employment proxy on a hand-checkable 4-zone toy (Phase 3 M1)."""

from pathlib import Path

import h3
import numpy as np
import polars as pl
import pytest
from shapely.geometry import Polygon

from glacies.cities import Attraction, ProxyWeights
from glacies.demand.attraction import (
    POPULATION_REFERENCE,
    AttractionError,
    build_attraction,
    hub_zones,
    read_hubs,
    score_rank,
    write_attraction,
)

BASE = h3.latlng_to_cell(12.05, 77.05, 8)
CELLS = [BASE, *sorted(h3.grid_ring(BASE, 1))[:3]]
CATEGORIES = ["office", "shop"]


def toy_zones() -> pl.DataFrame:
    """Building area 100/300/0/600 m² and job POIs 2/0/6/2 (office + shop).

    Shares: area .1/.3/0/.6, POIs .2/0/.6/.2. With weights 0.7/0.3 the scores are
    .13/.21/.18/.48 (sum 1), so the ranking is zone 3, 1, 2, 0. Zone 0's 50 amenity_other
    POIs must be ignored.
    """
    lat, lon = zip(*(h3.cell_to_latlng(c) for c in CELLS), strict=True)
    return pl.DataFrame(
        {
            "zone_idx": pl.Series([0, 1, 2, 3], dtype=pl.UInt32),
            "h3_cell": CELLS,
            "lat": lat,
            "lon": lon,
            "population": [100.0, 100.0, 100.0, 100.0],
            "building_area_m2_c65": [100.0, 300.0, 0.0, 600.0],
            "building_area_m2_c75": [100.0, 100.0, 100.0, 100.0],
            "poi_office": pl.Series([1, 0, 4, 2], dtype=pl.UInt32),
            "poi_shop": pl.Series([1, 0, 2, 0], dtype=pl.UInt32),
            "poi_amenity_other": pl.Series([50, 0, 0, 0], dtype=pl.UInt32),
        }
    )


def weights(name: str, area: float, pois: float, confidence: float = 0.65) -> ProxyWeights:
    return ProxyWeights(
        name=name, building_area=area, job_pois=pois, building_confidence=confidence
    )


def params(**overrides: object) -> Attraction:
    values: dict[str, object] = {
        "baseline": weights("baseline", 0.7, 0.3),
        "sensitivity": [weights("pois-only", 0.0, 1.0), weights("c75", 0.7, 0.3, 0.75)],
        "job_poi_categories": CATEGORIES,
        "opportunity_index_total": 1000,
        "hub_pass_rank": 0.25,  # top 1 of 4 zones
        "hub_report_rank": 0.5,  # top 2 of 4 zones
        "hub_pass_share": 0.5,
    }
    return Attraction.model_validate(values | overrides)


def inside(cell: str) -> Polygon:
    """A polygon well inside one cell."""
    return Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]).buffer(-0.0005)


def test_scores_match_hand_calculation() -> None:
    table = build_attraction(toy_zones(), params(), None).table

    assert table["employment_score"].to_list() == pytest.approx([0.13, 0.21, 0.18, 0.48])
    assert table["employment_score"].sum() == pytest.approx(1.0)
    assert table["opportunity_index"].to_list() == pytest.approx([130, 210, 180, 480])
    assert table["score_rank"].to_list() == [4, 2, 3, 1]
    assert table["building_share"].to_list() == pytest.approx([0.1, 0.3, 0.0, 0.6])
    assert table["job_poi_share"].to_list() == pytest.approx([0.2, 0.0, 0.6, 0.2])


def test_ties_rank_by_zone_index() -> None:
    assert score_rank(np.array([0.2, 0.5, 0.2, 0.1])).tolist() == [2, 1, 3, 4]


def test_hub_check_on_the_toy() -> None:
    # Hub "North" covers zones 3 and 1 (ranks 1 and 2); "South" covers zone 0 (rank 4).
    hubs = [("North", inside(CELLS[3]).union(inside(CELLS[1]))), ("South", inside(CELLS[0]))]

    build = build_attraction(toy_zones(), params(), hubs)

    check = build.sensitivity[0].hub_check
    assert check is not None
    # Hub zones {0, 1, 3}: top 1 = {3} -> 1/3; top 2 = {3, 1} -> 2/3.
    assert check.hub_zones == 3
    assert check.share_in_pass_rank == pytest.approx(1 / 3)
    assert check.share_in_report_rank == pytest.approx(2 / 3)
    assert not check.passed  # 1/3 < 0.5
    # Score share .13 + .21 + .48 = .82 over population share .75.
    assert check.concentration == pytest.approx(0.82 / 0.75)
    north, south = check.hubs
    assert (north.hub, north.zones, north.in_pass_rank, north.in_report_rank) == ("North", 2, 1, 2)
    assert (south.zones, south.best_rank_share) == (1, 1.0)


def test_hub_zones_need_a_real_overlap() -> None:
    far = Polygon([(10, 10), (10.01, 10), (10.01, 10.01)])

    found = hub_zones([("Far", far), ("Here", inside(CELLS[2]))], toy_zones())

    assert found.rows() == [("Here", 2)]


def test_sensitivity_includes_population_reference() -> None:
    rows = build_attraction(toy_zones(), params(), None).sensitivity

    assert [r.weighting for r in rows] == ["baseline", "pois-only", "c75", POPULATION_REFERENCE]
    assert rows[0].rank_correlation == pytest.approx(1.0)
    assert rows[0].top_decile_overlap == 1.0
    assert rows[-1].building_area is None
    assert rows[-1].rank_correlation is None  # toy population is constant


def test_missing_inputs_are_reported() -> None:
    with pytest.raises(AttractionError, match="poi_craft"):
        build_attraction(toy_zones(), params(job_poi_categories=["craft"]), None)
    no_area = toy_zones().with_columns(pl.lit(0.0).alias("building_area_m2_c65"))
    with pytest.raises(AttractionError, match="zero in every zone"):
        build_attraction(no_area, params(), None)


def test_weights_must_sum_to_one() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        weights("bad", 0.7, 0.4)


def test_read_hubs_strips_names(tmp_path: Path) -> None:
    path = tmp_path / "hubs.geojson"
    path.write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", '
        '"properties": {"name": "Electronic City\\n"}, "geometry": {"type": "Polygon", '
        '"coordinates": [[[77.0, 12.0], [77.01, 12.0], [77.01, 12.01], [77.0, 12.0]]]}}]}',
        encoding="utf-8",
    )

    ((name, _),) = read_hubs(path)

    assert name == "Electronic City"
    with pytest.raises(AttractionError, match="not found"):
        read_hubs(tmp_path / "missing.geojson")


def test_output_is_deterministic_and_labelled(tmp_path: Path) -> None:
    hubs = [("North", inside(CELLS[3]))]
    outputs = []
    for run in ("a", "b"):
        build = build_attraction(toy_zones(), params(), hubs)
        manifest = write_attraction(
            build,
            tmp_path / run / "attraction",
            city="toy",
            params=params(),
            zones_manifest_sha256="0" * 64,
            hubs_path=None,
            hub_names=["North", "Nowhere"],
        )
        outputs.append(manifest.outputs)
    assert outputs[0] == outputs[1]
    assert manifest.hubs_missing == ["Nowhere"]
    text = (tmp_path / "b" / "attraction" / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "Estimated Opportunity Index" in text
    assert "not a count of jobs" in text
    assert "**PASSED**" in text  # North's only zone ranks first
    assert "`employment_score`: estimated" in text
