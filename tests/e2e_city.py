"""Build Toyville with demand and assignment for the browser tests (web/e2e).

``uv run python -m tests.e2e_city <folder>`` writes ``<folder>/data``; point the API and the
worker at it with ``GLACIES_DATA_DIR`` and ``GLACIES_CITIES_DIR=tests/fixtures/cities``.
"""

import os
import shutil
import sys
from pathlib import Path

from tests import toy_city


def main(folder: Path) -> None:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    city = toy_city.build_in(folder, os.environ.__setitem__)
    toy_city.assign(city)
    print(f"Toyville built in {folder / 'data'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
