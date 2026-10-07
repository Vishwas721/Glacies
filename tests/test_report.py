"""Accessibility report pieces (Phase 3 M4): classes, Markdown/HTML, GeoParquet."""

import json
from pathlib import Path

import h3
import numpy as np
import polars as pl
import pyarrow.parquet as pq
import shapely

from glacies.analytics.report import (
    Block,
    Bullets,
    Heading,
    Image,
    Para,
    Table,
    class_labels,
    classify,
    to_html,
    to_markdown,
    write_geoparquet,
)

PNG = b"\x89PNG\r\n\x1a\n"


def test_classes_and_labels() -> None:
    values = np.array([0.0, 0.0005, 0.001, 0.02, 0.5])

    # Zero is "none" (-1); breaks are lower-inclusive for the next class.
    assert classify(values, (0.001, 0.01, 0.1)).tolist() == [-1, 0, 1, 2, 3]
    assert class_labels((0.001, 0.01, 0.1), "{:.1%}") == [
        "< 0.1%",
        "0.1% - 1.0%",
        "1.0% - 10.0%",
        "≥ 10.0%",
    ]


def test_markdown_and_html_render_the_same_blocks(tmp_path: Path) -> None:
    (tmp_path / "m.png").write_bytes(PNG + b"fake")
    blocks: list[Block] = [
        Heading(1, "Title"),
        Para("Reach **2.3%** of `est_jobs` <not jobs>"),
        Bullets(["one", "two"]),
        Table(["A", "B"], [["x", "1"]], [False, True]),
        Image("m.png", "A map"),
    ]

    md = to_markdown(blocks)
    assert "# Title" in md
    assert "| A | B |\n|---|---:|\n| x | 1 |" in md
    assert "![A map](m.png)" in md
    page = to_html(blocks, "T", tmp_path)
    assert "<strong>2.3%</strong>" in page
    assert "<code>est_jobs</code>" in page
    assert "&lt;not jobs&gt;" in page  # escaped
    assert 'src="data:image/png;base64,' in page  # self-contained
    assert '<td class="r">1</td>' in page


def test_geoparquet_has_geo_metadata_and_hexagons(tmp_path: Path) -> None:
    cells = [h3.latlng_to_cell(12.97, 77.59, 8), h3.latlng_to_cell(13.0, 77.6, 8)]
    frame = pl.DataFrame({"zone_idx": pl.Series([0, 1], dtype=pl.UInt32), "h3_cell": cells})
    path = tmp_path / "z.geoparquet"

    write_geoparquet(frame, cells, path)

    table = pq.read_table(path)
    geo = json.loads(table.schema.metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert geo["primary_column"] == "geometry"
    assert geo["columns"]["geometry"]["encoding"] == "WKB"
    assert "crs" not in geo["columns"]["geometry"]  # default: OGC:CRS84, lon/lat
    polygon = shapely.from_wkb(table.column("geometry")[0].as_py())
    assert len(polygon.exterior.coords) == 7  # six corners, closed
    lat, lon = h3.cell_to_latlng(cells[0])
    assert polygon.contains(shapely.Point(lon, lat))
    assert table.column("zone_idx").to_pylist() == [0, 1]
