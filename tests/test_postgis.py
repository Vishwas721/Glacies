import os
from datetime import date

import polars as pl
import pytest

from glacies.db.postgis import layers, load, pg_type, zone_wkt
from glacies.model.transit.build import FeedInput, build_transit
from glacies.model.zones.grid import make_zones
from glacies.validate.gtfs.report import Thresholds
from tests.gtfs_edit import TOY_FEED

BBOX = (77.0, 12.0, 77.1, 12.1)
DATABASE_URL = os.environ.get("GLACIES_TEST_DATABASE_URL")


@pytest.fixture(scope="module")
def transit() -> dict[str, pl.DataFrame]:
    feed = FeedInput("toy", "v1", "0" * 64, TOY_FEED)
    return build_transit(
        [feed], service_date=date(2026, 10, 13), bbox=BBOX, thresholds=Thresholds()
    ).tables


@pytest.fixture(scope="module")
def zones() -> pl.DataFrame:
    return make_zones(BBOX, 8).head(5).with_columns(pl.lit(1.5).alias("population"))


def test_pg_types() -> None:
    assert pg_type(pl.UInt32()) == "bigint"  # no unsigned types in PostgreSQL
    assert pg_type(pl.Float64()) == "double precision"
    assert pg_type(pl.String()) == "text"
    with pytest.raises(ValueError, match="no PostgreSQL type"):
        pg_type(pl.List(pl.Int64))


def test_zone_wkt_is_a_closed_hexagon(zones: pl.DataFrame) -> None:
    wkt = zone_wkt(zones["h3_cell"][0])
    points = wkt.removeprefix("POLYGON((").removesuffix("))").split(", ")

    assert len(points) == 7
    assert points[0] == points[-1]


def test_layers(transit: dict[str, pl.DataFrame], zones: pl.DataFrame) -> None:
    by_name = {layer.name: layer for layer in layers(transit, zones)}

    lines = by_name["pattern_lines"].frame
    assert lines.height == transit["patterns"].height
    first = lines.row(0, named=True)
    assert first["wkt"] == "LINESTRING(77.02 12.02, 77.03 12.03, 77.04 12.04)"  # stops A, B, C
    assert first["trips"] == 2  # T1 and T2
    assert first["mode"] == "bus"
    stops = by_name["stops"].frame
    assert stops.filter(pl.col("source_stop_id") == "A")["wkt"][0] == "POINT(77.02 12.02)"
    assert "lat" not in stops.columns
    assert by_name["zones"].frame.height == 5


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="set GLACIES_TEST_DATABASE_URL to a PostGIS db")
def test_round_trip_through_postgis(transit: dict[str, pl.DataFrame], zones: pl.DataFrame) -> None:
    import psycopg

    assert DATABASE_URL is not None
    counts = load(DATABASE_URL, "glacies_test", layers(transit, zones))
    counts_again = load(DATABASE_URL, "glacies_test", layers(transit, zones))  # replaces

    assert counts == counts_again == {"zones": 5, "stops": 6, "pattern_lines": 2}
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT count(*), bool_and(ST_IsValid(geom)), min(ST_NPoints(geom)) "
            "FROM glacies_test.zones"
        ).fetchone()
        assert row == (5, True, 7)
        srid = conn.execute("SELECT Find_SRID('glacies_test', 'stops', 'geom')").fetchone()
        assert srid == (4326,)
        length = conn.execute(
            "SELECT ST_Length(geom::geography) FROM glacies_test.pattern_lines "
            "WHERE pattern_idx = 0"
        ).fetchone()
        assert length is not None
        assert 3_000 < length[0] < 3_200  # A to C is about 3.1 km


def test_rejects_unsafe_schema_names() -> None:
    with pytest.raises(ValueError, match="invalid schema"):
        load("postgresql://unused", "bad; drop", [])
