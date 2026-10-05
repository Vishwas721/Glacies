from pathlib import Path

from glacies._geoenv import isolate_geo_data


def test_drops_variables_outside_the_environment(tmp_path: Path) -> None:
    inside = str(tmp_path / "env" / "share" / "proj")
    env = {
        "PROJ_DATA": inside,
        "PROJ_LIB": r"C:\Somewhere\Else\proj",
        "GDAL_DATA": r"C:\Program Files\PostgreSQL\17\gdal-data",
        "PATH": "untouched",
    }

    removed = isolate_geo_data(env, prefix=str(tmp_path / "env"))

    assert removed == ["PROJ_LIB", "GDAL_DATA"]
    assert env == {"PROJ_DATA": inside, "PATH": "untouched"}
