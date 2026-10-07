from pathlib import Path

import pytest

from glacies.cities import CityConfigError, load_city
from glacies.provenance import DataNature

FIXTURES = Path(__file__).parent / "fixtures" / "cities"


def test_loads_toy_city() -> None:
    city = load_city(FIXTURES / "toyville" / "city.toml")

    assert city.city.id == "toyville"
    assert city.city.bbox == (77.0, 12.0, 77.1, 12.1)
    assert city.zoning.resolution == 8
    assert sorted(city.sources) == [
        "toy_buildings",
        "toy_gtfs",
        "toy_landcover",
        "toy_osm",
        "toy_population",
    ]
    assert city.sources["toy_population"].nature is DataNature.ESTIMATED
    assert city.sources["toy_gtfs"].download_url is None


def test_source_lookup_names_known_sources() -> None:
    city = load_city(FIXTURES / "toyville" / "city.toml")

    assert city.source("toy_gtfs").kind == "gtfs"
    with pytest.raises(
        CityConfigError, match="toy_buildings, toy_gtfs, toy_landcover, toy_osm, toy_population"
    ):
        city.source("nope")


def test_repository_cities_are_valid() -> None:
    repo_cities = Path(__file__).parents[1] / "cities"
    for path in sorted(repo_cities.glob("*/city.toml")):
        city = load_city(path)
        assert city.city.id == path.parent.name


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "city.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_rejects_inverted_bbox(tmp_path: Path) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    inverted = original.replace("[77.0, 12.0, 77.1, 12.1]", "[77.1, 12.0, 77.0, 12.1]")
    path = _write(tmp_path, inverted)

    with pytest.raises(CityConfigError, match="bbox"):
        load_city(path)


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    path = _write(tmp_path, original.replace('kind = "gtfs"', 'kind = "gtfs"\nverfied = true'))

    with pytest.raises(CityConfigError, match="verfied"):
        load_city(path)


def test_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(CityConfigError, match="not found"):
        load_city(tmp_path / "missing.toml")


def test_rejects_inverted_coverage_reference(tmp_path: Path) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    inverted = original.replace("route_count_min = 2\n", "route_count_min = 10\n")
    path = _write(tmp_path, inverted)

    with pytest.raises(CityConfigError, match="route_count_min"):
        load_city(path)


def test_rejects_invalid_route_number_pattern(tmp_path: Path) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    broken = original.replace(r"route_number_pattern = '^\S+'", "route_number_pattern = '(['")
    path = _write(tmp_path, broken)

    with pytest.raises(CityConfigError, match="route_number_pattern"):
        load_city(path)


def test_network_section(tmp_path: Path) -> None:
    city = load_city(FIXTURES / "toyville" / "city.toml")

    assert city.network is not None
    assert city.network.feeds == ["toy_gtfs"]
    assert city.network.service_date.isoformat() == "2026-10-13"


@pytest.mark.parametrize(
    ("feeds", "message"),
    [
        ('["nope"]', "not a source"),
        ('["toy_population"]', "not a GTFS source"),
        ('["toy_gtfs", "toy_gtfs"]', "unique"),
    ],
)
def test_rejects_bad_network_feeds(tmp_path: Path, feeds: str, message: str) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    path = _write(tmp_path, original.replace('feeds = ["toy_gtfs"]', f"feeds = {feeds}"))

    with pytest.raises(CityConfigError, match=message):
        load_city(path)


def test_walk_defaults_and_bengaluru_overrides() -> None:
    toy = load_city(FIXTURES / "toyville" / "city.toml")
    bengaluru = load_city(Path(__file__).parents[1] / "cities" / "bengaluru" / "city.toml")

    assert "trunk" in toy.walk.highways
    assert "motorway" not in toy.walk.highways
    assert toy.walk.max_snap_m == 300.0
    assert bengaluru.walk.highways == toy.walk.highways
    assert bengaluru.walk.exclude_access == ["no"]  # private ways are walkable in Bengaluru
    assert bengaluru.walk.snap_to_largest_component


@pytest.mark.parametrize("thresholds", ["[]", "[0.75, 0.65]", "[0.0]", "[0.7, 0.7]", "[1.5]"])
def test_rejects_bad_building_thresholds(tmp_path: Path, thresholds: str) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    path = _write(
        tmp_path,
        original.replace(
            "resolution = 8", f"resolution = 8\nbuilding_confidence_thresholds = {thresholds}"
        ),
    )

    with pytest.raises(CityConfigError, match="building_confidence_thresholds"):
        load_city(path)


def test_routing_parameters() -> None:
    bengaluru = load_city(Path(__file__).parents[1] / "cities" / "bengaluru" / "city.toml")

    routing = bengaluru.routing
    assert (routing.max_rounds, routing.walking_speed_m_s, routing.min_transfer_time_s) == (
        4,
        1.2,
        60,
    )
    assert (routing.max_access_walk_m, routing.max_transfer_walk_m) == (800.0, 400.0)
    assert routing.station_entry_s == {"metro": 240}


@pytest.mark.parametrize(
    ("table", "message"),
    [("{ subway = 240 }", "unknown mode 'subway'"), ("{ metro = -1 }", "must be >= 0")],
)
def test_rejects_bad_station_entry_times(tmp_path: Path, table: str, message: str) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    path = _write(tmp_path, original + f"\n[routing]\nstation_entry_s = {table}\n")

    with pytest.raises(CityConfigError, match=message):
        load_city(path)


def test_rejects_zero_rounds(tmp_path: Path) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    path = _write(tmp_path, original + "\n[routing]\nmax_rounds = 0\n")

    with pytest.raises(CityConfigError, match="max_rounds"):
        load_city(path)


def test_attraction_settings() -> None:
    bengaluru = load_city(Path(__file__).parents[1] / "cities" / "bengaluru" / "city.toml")

    attraction = bengaluru.attraction
    assert attraction is not None
    base = attraction.baseline
    assert (base.building_area, base.job_pois, base.building_confidence) == (0.7, 0.3, 0.65)
    assert "amenity_other" not in attraction.job_poi_categories
    assert attraction.opportunity_index_total == 5_000_000
    assert (attraction.hub_pass_rank, attraction.hub_report_rank) == (0.2, 0.05)
    assert len(attraction.sensitivity) >= 3
    hubs = Path(__file__).parents[1] / "cities" / "bengaluru" / str(attraction.validation_hubs)
    assert hubs.is_file()


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (("confidence = 0.65", "confidence = 0.5"), "not one of"),
        (('name = "equal"', 'name = "baseline"'), "unique"),
        (("job_pois = 0.3", "job_pois = 0.4"), "sum to 1"),
    ],
)
def test_rejects_bad_attraction(tmp_path: Path, edit: tuple[str, str], message: str) -> None:
    original = (FIXTURES / "toyville" / "city.toml").read_text(encoding="utf-8")
    path = _write(tmp_path, original.replace(*edit, 1))

    with pytest.raises(CityConfigError, match=message):
        load_city(path)
