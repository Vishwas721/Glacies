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
    assert sorted(city.sources) == ["toy_gtfs", "toy_population"]
    assert city.sources["toy_population"].nature is DataNature.ESTIMATED
    assert city.sources["toy_gtfs"].download_url is None


def test_source_lookup_names_known_sources() -> None:
    city = load_city(FIXTURES / "toyville" / "city.toml")

    assert city.source("toy_gtfs").kind == "gtfs"
    with pytest.raises(CityConfigError, match="toy_gtfs, toy_population"):
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
