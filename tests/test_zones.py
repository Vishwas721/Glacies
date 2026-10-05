from datetime import date
from pathlib import Path
from typing import Any

import h3
import numpy as np
import polars as pl
import pytest
import rasterio
from rasterio.transform import from_origin

from glacies.model.transit.build import FeedInput, build_transit
from glacies.model.zones.build import (
    InputRef,
    ZoneInputs,
    ZonesBuild,
    build_zones,
    population_check,
    stop_modes,
    write_zones,
)
from glacies.model.zones.grid import make_zones
from glacies.model.zones.pois import extract_pois
from glacies.validate.gtfs.report import Thresholds
from tests.gtfs_edit import TOY_FEED

BBOX = (77.0, 12.0, 77.1, 12.1)
RES = 8
FIXTURES = Path(__file__).parent / "fixtures"
HOT = (12.0504, 77.0504)  # (lat, lon) of the 1000-person pixel
POP_RES = 1 / 1200  # WorldPop 100 m grid
LC_RES = 1 / 12000  # WorldCover 10 m grid
EXTENT = (76.99, 12.11)  # raster top-left (lon, lat); rasters cover the bbox plus 0.01 deg


def _write_raster(path: Path, data: np.ndarray, res: float, nodata: float) -> None:
    with rasterio.open(
        path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1], count=1,
        dtype=data.dtype, crs="EPSG:4326", transform=from_origin(*EXTENT, res, res), nodata=nodata,
    ) as dst:  # fmt: skip
        dst.write(data, 1)


@pytest.fixture
def population_raster(tmp_path: Path) -> Path:
    size = round(0.12 / POP_RES)
    data = np.ones((size, size), dtype=np.float32)
    nd_row, nd_col = int((EXTENT[1] - 12.06) / POP_RES), int((77.06 - EXTENT[0]) / POP_RES)
    data[nd_row : nd_row + 2, nd_col : nd_col + 2] = -99999.0  # nodata block inside the bbox
    row = int((EXTENT[1] - HOT[0]) / POP_RES)
    col = int((HOT[1] - EXTENT[0]) / POP_RES)
    data[row, col] = 1000.0
    path = tmp_path / "pop.tif"
    _write_raster(path, data, POP_RES, -99999.0)
    return path


@pytest.fixture
def landcover_raster(tmp_path: Path) -> Path:
    size = round(0.12 / LC_RES)
    data = np.full((size, size), 40, dtype=np.uint8)  # cropland
    data[:, : round((77.05 - EXTENT[0]) / LC_RES)] = 50  # built-up west of 77.05
    path = tmp_path / "lc.tif"
    _write_raster(path, data, LC_RES, 0)
    return path


@pytest.fixture
def buildings_csv(tmp_path: Path) -> Path:
    path = tmp_path / "buildings.csv.gz"
    frame = pl.DataFrame(
        {
            "latitude": [12.0500, 12.0501, 12.0800, 12.5000],
            "longitude": [77.0200, 77.0201, 77.0800, 77.5000],
            "area_in_meters": [100.0, 50.0, 30.0, 10.0],
            "confidence": [0.70, 0.80, 0.90, 0.90],
            "geometry": ["POLYGON EMPTY"] * 4,
        }
    )
    frame.write_csv(path, compression="gzip")
    return path


@pytest.fixture
def transit() -> dict[str, pl.DataFrame]:
    feed = FeedInput("toy", "v1", "0" * 64, TOY_FEED)
    return build_transit(
        [feed], service_date=date(2026, 10, 13), bbox=BBOX, thresholds=Thresholds()
    ).tables


@pytest.fixture
def built(
    population_raster: Path,
    landcover_raster: Path,
    buildings_csv: Path,
    transit: dict[str, pl.DataFrame],
) -> ZonesBuild:
    inputs = ZoneInputs(
        population_raster=population_raster,
        landcover_raster=landcover_raster,
        buildings_csv=buildings_csv,
        osm_file=FIXTURES / "osm" / "toy_pois.osm",
        transit_stops=transit["stops"],
        transit_stop_modes=stop_modes(transit),
    )
    return build_zones(inputs, bbox=BBOX, resolution=RES, thresholds=[0.65, 0.75])


def zone_at(result: ZonesBuild, lat: float, lon: float) -> dict[str, Any]:
    cell = h3.latlng_to_cell(lat, lon, RES)
    return result.tables["zones"].filter(pl.col("h3_cell") == cell).row(0, named=True)


# --- grid -----------------------------------------------------------------------------------


def test_zones_cover_the_bbox_and_are_ordered() -> None:
    zones = make_zones(BBOX, RES)

    assert zones["h3_cell"].to_list() == sorted(zones["h3_cell"].to_list())
    assert zones["zone_idx"].to_list() == list(range(zones.height))
    for lat, lon in [(12.0, 77.0), (12.1, 77.1), (12.05, 77.05), (12.0, 77.1)]:
        assert h3.latlng_to_cell(lat, lon, RES) in set(zones["h3_cell"])
    assert float(zones["area_m2"].min()) > 600_000  # type: ignore[arg-type]  # ~0.74 km2


# --- population -----------------------------------------------------------------------------


def test_population_is_conserved(built: ZonesBuild) -> None:
    conservation, ratio = population_check(built.stats)

    assert conservation < 1e-9
    assert ratio >= 1.0  # zones extend slightly past the bbox
    assert built.tables["zones"]["population"].sum() == pytest.approx(
        built.stats["population_zones"], abs=0.5
    )


def test_hot_pixel_lands_in_its_zone(built: ZonesBuild) -> None:
    assert zone_at(built, *HOT)["population"] >= 1000


def test_population_matches_an_independent_pixel_assignment(
    built: ZonesBuild, population_raster: Path
) -> None:
    """Oracle: put every pixel centre in its H3 cell directly and sum (nodata as zero)."""
    with rasterio.open(population_raster) as src:
        data = src.read(1).astype(np.float64)
        data[data == src.nodata] = 0.0
        transform = src.transform
    rows, cols = np.indices(data.shape)
    lons = transform.c + (cols + 0.5) * transform.a
    lats = transform.f + (rows + 0.5) * transform.e
    cells = [h3.latlng_to_cell(y, x, RES) for y, x in zip(lats.ravel(), lons.ravel(), strict=True)]
    expected = (
        pl.DataFrame({"h3_cell": cells, "value": data.ravel()})
        .group_by("h3_cell")
        .agg(pl.col("value").sum())
    )
    actual = built.tables["zones"].select("h3_cell", "population")
    joined = actual.join(expected, on="h3_cell", how="left").fill_null(0.0)

    # Pixel centres falling exactly on a hexagon edge may go either way; allow a pixel or two.
    assert float((joined["population"] - joined["value"]).abs().max()) <= 2.0  # type: ignore[arg-type]
    assert joined["population"].sum() == pytest.approx(joined["value"].sum(), abs=2.0)
    nodata_zone = zone_at(built, 12.06, 77.06)
    assert nodata_zone["population"] < (
        joined.filter(pl.col("h3_cell") == nodata_zone["h3_cell"])["value"][0] + 1
    )


# --- land cover -----------------------------------------------------------------------------


def test_landcover_shares(built: ZonesBuild) -> None:
    west = zone_at(built, 12.05, 77.02)
    east = zone_at(built, 12.05, 77.08)
    zones = built.tables["zones"]
    share_cols = [c for c in zones.columns if c.startswith("landcover_")]

    assert west["landcover_built"] == pytest.approx(1.0)
    assert east["landcover_cropland"] == pytest.approx(1.0)
    totals = zones.select(pl.sum_horizontal(share_cols).alias("t"))["t"]
    assert ((totals - 1.0).abs() < 1e-9).all()


# --- buildings ------------------------------------------------------------------------------


def test_buildings_by_confidence(built: ZonesBuild) -> None:
    pair = zone_at(built, 12.05, 77.02)
    single = zone_at(built, 12.08, 77.08)

    assert (pair["building_count_c65"], pair["building_area_m2_c65"]) == (2, 150.0)
    assert (pair["building_count_c75"], pair["building_area_m2_c75"]) == (1, 50.0)
    assert (single["building_count_c75"], single["building_area_m2_c75"]) == (1, 30.0)
    assert built.stats["buildings_outside_zones"] == 1


# --- POIs -----------------------------------------------------------------------------------


def test_poi_categories() -> None:
    pois, skipped = extract_pois(FIXTURES / "osm" / "toy_pois.osm", BBOX)
    by_id = dict(pois.select(pl.concat_str("osm_type", "osm_id"), "category").iter_rows())

    assert by_id == {
        "node1": "office",
        "node2": "shop",
        "node3": "health",
        "node5": "food",
        "node6": "craft",
        "node8": "amenity_other",
        "node9": "office",  # office wins over shop
        "node10": "health",
        "way100": "education",
        "way101": "industrial",
    }
    assert skipped == {"not_a_place": 1, "relation": 1}  # the bench; the multipolygon


def test_way_pois_sit_at_their_centre() -> None:
    pois, _ = extract_pois(FIXTURES / "osm" / "toy_pois.osm", BBOX)
    school = pois.filter(pl.col("osm_id") == 100).row(0, named=True)

    # the closed ring repeats its first node, so the mean is pulled slightly towards it
    assert school["lat"] == pytest.approx(12.0804, abs=1e-4)
    assert school["lon"] == pytest.approx(77.0804, abs=1e-4)


def test_poi_counts_per_zone(built: ZonesBuild) -> None:
    zone = zone_at(built, 12.05, 77.02)

    assert zone["poi_office"] >= 1
    assert built.stats["pois"] == 10


# --- stops ----------------------------------------------------------------------------------


def test_stops_by_mode(built: ZonesBuild) -> None:
    zones = built.tables["zones"]

    assert zones["stops_bus"].sum() == 3  # A, B, C
    assert zones["stops_metro"].sum() == 2  # P1, D
    assert zone_at(built, 12.05, 77.05)["stops_metro"] == 1  # D
    assert built.stats["stops_outside_zones"] == 0


# --- output ---------------------------------------------------------------------------------


def write(result: ZonesBuild, out: Path) -> str:
    manifest = write_zones(
        result, out, city="toyville", bbox=BBOX, resolution=RES, thresholds=[0.65, 0.75],
        inputs=[InputRef(dataset="toy_pop", snapshot="v1", checksum_sha256="0" * 64)],
        transit_stops_sha256="1" * 64,
    )  # fmt: skip
    return manifest.model_dump_json()


def test_output_is_byte_identical(built: ZonesBuild, tmp_path: Path) -> None:
    assert write(built, tmp_path / "one") == write(built, tmp_path / "two")
    for path in sorted((tmp_path / "one").iterdir()):
        assert path.read_bytes() == (tmp_path / "two" / path.name).read_bytes(), path.name


def test_report_states_labels_and_checks(built: ZonesBuild, tmp_path: Path) -> None:
    write(built, tmp_path / "out")

    report = (tmp_path / "out" / "BUILD_REPORT.md").read_text(encoding="utf-8")
    assert "## Population (Estimated, WorldPop)" in report
    assert "- `poi_*`: observed" in report
    assert "Confidence ≥ 0.75: 2" in report
