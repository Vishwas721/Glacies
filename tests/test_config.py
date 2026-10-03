from pathlib import Path

import pytest

from glacies.config import Settings


def test_defaults_point_at_local_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GLACIES_CITY", raising=False)
    settings = Settings(_env_file=None)

    assert settings.processed_dir == Path("data/processed")
    assert settings.city_config_path == Path("cities/bengaluru/city.toml")


def test_environment_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLACIES_CITY", "helsinki")
    monkeypatch.setenv("GLACIES_RANDOM_SEED", "7")
    settings = Settings(_env_file=None)

    assert settings.city == "helsinki"
    assert settings.random_seed == 7
