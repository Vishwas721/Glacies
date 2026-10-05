import math
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from glacies.cities import Walk
from glacies.model.walk.build import WalkBuild, build_walk
from glacies.model.walk.extract import ExtractStats, extract_walk_segments
from glacies.model.walk.writer import write_walk

TOY_OSM = Path(__file__).parent / "fixtures" / "osm" / "toy.osm"
BBOX = (77.0, 12.0, 77.1, 12.1)
UTM = "EPSG:32643"

# stop_idx -> (lat, lon), chosen against the toy network in fixtures/osm/toy.osm
STOPS = pl.DataFrame(
    {
        "stop_idx": [0, 1, 2, 3],
        "lat": [12.0200, 12.0205, 12.0101, 12.0500],
        "lon": [77.0200, 77.0250, 77.0101, 77.0500],
        "source_stop_id": ["A", "M", "P1", "D"],
        "name": ["On node 1", "Beside edge 1-2", "Next to the island", "Motorway end"],
    }
)


def run(walk: Walk | None = None) -> tuple[WalkBuild, ExtractStats]:
    walk = walk or Walk()
    segments, stats = extract_walk_segments(TOY_OSM, BBOX, walk)
    return build_walk(segments, STOPS, walk, UTM), stats


def link(result: WalkBuild, stop_idx: int) -> dict[str, Any]:
    return result.tables["stop_links"].filter(pl.col("stop_idx") == stop_idx).row(0, named=True)


# --- extraction -----------------------------------------------------------------------------


def test_tag_rules_and_clipping() -> None:
    _, stats = run()

    assert stats.ways_excluded == {
        "highway=motorway": 1,
        "highway=construction": 1,
        "foot=no": 1,
        "access=private": 1,
    }
    # residential x3 (square, clipped road, private-but-foot=yes), footway x2, path, trunk
    assert stats.ways_kept == {"residential": 3, "footway": 2, "path": 1, "trunk": 1}
    assert stats.segments_outside_bbox == 1


def test_highway_list_is_configurable() -> None:
    _, stats = run(Walk(highways=["residential"]))

    assert stats.ways_kept == {"residential": 3}
    assert stats.ways_excluded["highway=trunk"] == 1


# --- graph ----------------------------------------------------------------------------------


def test_nodes_edges_and_duplicates() -> None:
    result, _ = run()
    nodes, edges = result.tables["nodes"], result.tables["edges"]

    assert nodes["osm_node_id"].to_list() == [1, 2, 3, 4, 5, 9, 10, 12, 13]
    assert nodes["node_idx"].to_list() == list(range(9))
    assert edges.height == 8  # 9 segments, footway 1-2 duplicates the square's first side
    assert result.stats["duplicate_segments"] == 1
    assert (edges["from_node"] < edges["to_node"]).all()
    first = edges.row(0, named=True)
    assert (first["from_node"], first["to_node"], first["osm_way_id"]) == (0, 1, 100)


def test_edge_lengths_are_metres() -> None:
    result, _ = run()
    side = result.tables["edges"].row(0, named=True)  # node 1 -> 2: 0.01 deg of longitude

    expected = 6_371_008.8 * math.radians(0.01) * math.cos(math.radians(12.02))
    assert side["length_m"] == pytest.approx(expected, abs=0.5)


def test_components_put_the_largest_first() -> None:
    result, _ = run()
    component = dict(result.tables["nodes"].select("osm_node_id", "component").iter_rows())

    assert {n for n, c in component.items() if c == 0} == {1, 2, 3, 4, 5, 12, 13}
    assert component[9] == component[10] == 1
    assert result.stats["components"] == 2
    assert result.stats["largest_component_share"] == pytest.approx(7 / 9, abs=1e-4)


# --- snapping -------------------------------------------------------------------------------


def test_stop_on_a_node_snaps_with_zero_distance_to_lowest_edge() -> None:
    result, _ = run()
    a = link(result, 0)

    assert a["edge_idx"] == 0  # edges 1-2 and 1-4 tie at 0 m; the lower index wins
    assert a["distance_m"] == pytest.approx(0, abs=0.01)
    assert a["fraction"] == pytest.approx(0, abs=1e-6)
    assert not a["flagged"]


def test_stop_beside_an_edge_snaps_to_its_middle() -> None:
    result, _ = run()
    m = link(result, 1)

    assert m["edge_idx"] == 0
    assert m["fraction"] == pytest.approx(0.5, abs=0.01)
    assert m["distance_m"] == pytest.approx(55.3, abs=1.0)  # 0.0005 deg of latitude
    assert m["snap_lat"] == pytest.approx(12.02, abs=1e-5)


def test_stops_are_kept_off_isolated_fragments_and_flagged() -> None:
    result, _ = run()
    p1 = link(result, 2)

    island_nodes = result.tables["nodes"].filter(pl.col("component") == 1)["node_idx"].to_list()
    edge = result.tables["edges"].filter(pl.col("edge_idx") == p1["edge_idx"]).row(0, named=True)
    assert edge["from_node"] not in island_nodes
    assert p1["distance_m"] > 1_000
    assert p1["flagged"]
    assert result.stats["stops_flagged"] == 2  # P1 and the motorway-only stop D


def test_snapping_to_any_component_when_allowed() -> None:
    result, _ = run(Walk(snap_to_largest_component=False))
    p1 = link(result, 2)

    assert p1["distance_m"] < 50
    assert not p1["flagged"]


def test_snap_limit_is_configurable() -> None:
    result, _ = run(Walk(max_snap_m=50))

    assert link(result, 1)["flagged"]  # 55 m away


# --- output ---------------------------------------------------------------------------------


def write(out: Path) -> str:
    result, stats = run()
    manifest = write_walk(
        result, stats, out, city="toyville", bbox=BBOX, osm_snapshot="v1",
        osm_checksum_sha256="0" * 64, transit_stops_sha256="1" * 64, walk=Walk(),
        stop_names=STOPS.select("stop_idx", "source_stop_id", "name"),
    )  # fmt: skip
    return manifest.model_dump_json()


def test_output_is_byte_identical(tmp_path: Path) -> None:
    assert write(tmp_path / "one") == write(tmp_path / "two")
    for path in sorted((tmp_path / "one").iterdir()):
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes(), path.name


def test_report_lists_flagged_stops(tmp_path: Path) -> None:
    write(tmp_path / "out")

    report = (tmp_path / "out" / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "**Flagged (> 300 m): 2**" in report
    assert "Next to the island" in report
    assert "| highway=motorway | 1 |" in report
