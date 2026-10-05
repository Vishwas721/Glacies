"""Helpers for tests that derive broken or modified GTFS feeds from the toy feed."""

import shutil
from pathlib import Path

TOY_FEED = Path(__file__).parent / "fixtures" / "gtfs" / "toy_feed"


def copy_toy_feed(target: Path) -> Path:
    shutil.copytree(TOY_FEED, target)
    return target


def append(feed: Path, file: str, *lines: str) -> None:
    with (feed / file).open("a", encoding="utf-8", newline="\n") as handle:
        handle.writelines(f"{line}\n" for line in lines)


def replace(feed: Path, file: str, old: str, new: str) -> None:
    text = (feed / file).read_text(encoding="utf-8")
    assert old in text, f"{old!r} not in {file}"
    (feed / file).write_text(text.replace(old, new), encoding="utf-8", newline="\n")
