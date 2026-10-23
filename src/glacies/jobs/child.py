"""One simulation in its own process: ``python -m glacies.jobs.child <city> <scenario.json>``.

The worker runs this as a child so that cancelling can end it at once: the run spends minutes
inside Rust, where no Python-level signal or exception reaches it. Progress goes to stdout as
one JSON object per line; errors go to stderr and a non-zero exit code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from glacies.cities import load_city
from glacies.config import get_settings
from glacies.scenario.compare import BASELINE, compare
from glacies.scenario.runner import engine_versions, run_scenario

COMPARISON = "comparison"  # folder inside the result, next to accessibility/ and assignment/


def emit(**event: Any) -> None:
    print(json.dumps(event), flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m glacies.jobs.child <city> <scenario.json>", file=sys.stderr)
        return 2
    city, path = argv[0], Path(argv[1])
    settings = get_settings().model_copy(update={"city": city})
    config = load_city(settings.city_config_path)
    # One engine version for the run and its comparison: read twice, an edit to the source
    # tree during a long run would change the key and the comparison would miss the result.
    engine = engine_versions()
    outcome = run_scenario(
        settings,
        config,
        path,
        engine=engine,
        on_stage=lambda message: emit(event="stage", message=message),
        on_chunk=lambda done, total: emit(event="chunk", done=done, total=total),
    )
    emit(event="stage", message=COMPARISON)
    compare(
        settings, config, BASELINE, str(path), engine=engine, out_dir=outcome.out_dir / COMPARISON
    )
    emit(event="done", result_key=outcome.record.cache_key, cached=outcome.cached)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
