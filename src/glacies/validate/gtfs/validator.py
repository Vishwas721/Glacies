"""Entry point: validate one GTFS directory and build a report."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from glacies import __version__
from glacies.cities import CoverageReference
from glacies.validate.gtfs.common import Collector
from glacies.validate.gtfs.coverage import measure_coverage
from glacies.validate.gtfs.loader import load_feed
from glacies.validate.gtfs.report import Thresholds, ValidationReport, sort_findings
from glacies.validate.gtfs.semantic import check_semantics
from glacies.validate.gtfs.structural import check_structure


class ValidationOptions(BaseModel):
    dataset: str
    city: str
    snapshot: str
    input_checksum: str
    bbox: tuple[float, float, float, float]
    route_number_pattern: str | None = None
    coverage_reference: CoverageReference | None = None
    thresholds: Thresholds = Thresholds()


def validate_feed(directory: Path, options: ValidationOptions) -> ValidationReport:
    feed = load_feed(directory)
    out = Collector(options.thresholds.max_examples)
    check_structure(feed, out, options.thresholds)
    service_range = check_semantics(feed, out, options.thresholds, options.bbox)
    return ValidationReport(
        dataset=options.dataset,
        city=options.city,
        snapshot=options.snapshot,
        input_checksum=options.input_checksum,
        validator_version=__version__,
        row_counts={name: frame.height for name, frame in sorted(feed.tables.items())},
        service_range=service_range,
        coverage=measure_coverage(feed, options.route_number_pattern, options.coverage_reference),
        thresholds=options.thresholds,
        findings=sort_findings(out.findings),
    )
