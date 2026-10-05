"""GTFS validation report: findings, counts, coverage, and JSON/Markdown rendering.

Reports contain no timestamps so that validating the same snapshot twice is byte-identical.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from glacies.provenance import DataNature


class Severity(StrEnum):
    ERROR = "error"  # breaks the canonical model or routing
    WARNING = "warning"  # suspicious; usable, but results may be affected
    INFO = "info"  # facts worth knowing


_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


class Finding(BaseModel):
    rule: str
    severity: Severity
    file: str | None
    message: str
    count: int
    examples: list[str] = Field(default_factory=list)


class Thresholds(BaseModel):
    """Validator parameters. All are Assumed values chosen by the developer."""

    nature: DataNature = DataNature.ASSUMED
    max_speed_kmh: dict[str, float] = Field(
        default_factory=lambda: {
            "0": 70.0,  # tram
            "1": 120.0,  # metro / subway
            "2": 160.0,  # rail
            "3": 80.0,  # bus
            "11": 80.0,  # trolleybus
            "12": 120.0,  # monorail
        },
        description="Maximum plausible speed between consecutive stops, by GTFS route_type.",
    )
    default_max_speed_kmh: float = 150.0
    zero_time_hop_max_m: float = Field(
        default=100.0, description="Zero-second hops longer than this are flagged."
    )
    near_duplicate_stop_m: float = 5.0
    max_examples: int = 5


class Coverage(BaseModel):
    route_rows: int
    routes_with_trips: int
    distinct_route_numbers: int | None = None
    route_number_pattern: str | None = None
    routes_by_type: dict[str, int] = Field(default_factory=dict)
    stops_total: int
    stops_served: int
    reference_route_count_min: int | None = None
    reference_route_count_max: int | None = None
    reference_source: str | None = None
    reference_verified: bool | None = None
    ratio_min: float | None = None
    ratio_max: float | None = None


class ServiceRange(BaseModel):
    start_date: str
    end_date: str


class ValidationReport(BaseModel):
    dataset: str
    city: str
    snapshot: str
    input_checksum: str
    validator_version: str
    row_counts: dict[str, int]
    service_range: ServiceRange | None
    coverage: Coverage
    thresholds: Thresholds
    findings: list[Finding]

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity is severity)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity is Severity.ERROR]

    def to_json(self) -> str:
        return self.model_dump_json(indent=2) + "\n"

    def to_markdown(self) -> str:
        return _render_markdown(self)


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.rule, f.file or ""))


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _render_markdown(report: ValidationReport) -> str:
    cov = report.coverage
    lines = [
        f"# GTFS validation — `{report.dataset}` @ `{report.snapshot}`",
        "",
        f"City: `{report.city}` · Input checksum: `{report.input_checksum[:16]}…` · "
        f"Validator {report.validator_version}",
        "",
        "## Summary",
        "",
        f"**{report.count(Severity.ERROR)} errors · {report.count(Severity.WARNING)} warnings · "
        f"{report.count(Severity.INFO)} info**",
        "",
        "| File | Rows |",
        "|---|---:|",
        *(f"| {name}.txt | {rows:,} |" for name, rows in sorted(report.row_counts.items())),
        "",
    ]
    if report.service_range:
        lines += [
            f"Service dates: {report.service_range.start_date} → {report.service_range.end_date}",
            "",
        ]

    lines += [
        "## Coverage (Observed counts from the feed)",
        "",
        f"- Route rows in `routes.txt`: {cov.route_rows:,} ({cov.routes_with_trips:,} with trips)",
    ]
    if cov.distinct_route_numbers is not None:
        lines.append(
            f"- Distinct route numbers (pattern `{cov.route_number_pattern}`): "
            f"{cov.distinct_route_numbers:,}"
        )
    lines += [
        "- Routes by type: "
        + ", ".join(f"{k}: {v:,}" for k, v in sorted(cov.routes_by_type.items())),
        f"- Stops served by at least one trip: {cov.stops_served:,} of {cov.stops_total:,}",
    ]
    if cov.ratio_min is not None and cov.ratio_max is not None:
        verified = "verified" if cov.reference_verified else "**unverified**"
        lines += [
            f"- Reference route count (Assumed, {verified}): "
            f"{cov.reference_route_count_min:,} to {cov.reference_route_count_max:,} "
            f"— {cov.reference_source}",
            f"- **Coverage ratio: {cov.ratio_min:.0%} to {cov.ratio_max:.0%}** "
            "(feed route numbers ÷ reference; definitions may differ)",
        ]
    else:
        lines.append("- Coverage ratio: **not measured** (no reference route count configured)")
    lines.append("")

    lines += ["## Findings", ""]
    if not report.findings:
        lines += ["No findings.", ""]
    for severity in Severity:
        group = [f for f in report.findings if f.severity is severity]
        if not group:
            continue
        lines += [
            f"### {severity.value.capitalize()}s ({len(group)})",
            "",
            "| Rule | File | Count | Message | Examples |",
            "|---|---|---:|---|---|",
        ]
        lines += [
            f"| `{f.rule}` | {f.file or '—'} | {f.count:,} | {_cell(f.message)} | "
            f"{_cell(', '.join(f.examples)) or '—'} |"
            for f in group
        ]
        lines.append("")

    t = report.thresholds
    speeds = ", ".join(f"type {k}: {v:g} km/h" for k, v in sorted(t.max_speed_kmh.items()))
    lines += [
        "## Thresholds (Assumed)",
        "",
        f"- Max speed between stops: {speeds}; other types {t.default_max_speed_kmh:g} km/h",
        f"- Zero-time hops flagged above {t.zero_time_hop_max_m:g} m",
        f"- Near-duplicate stops: same name within {t.near_duplicate_stop_m:g} m",
        "",
    ]
    return "\n".join(lines)
