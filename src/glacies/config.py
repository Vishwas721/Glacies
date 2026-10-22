"""Runtime settings, loaded from environment variables and an optional ``.env`` file."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide configuration. Every field can be overridden with ``GLACIES_<NAME>``."""

    model_config = SettingsConfigDict(
        env_prefix="GLACIES_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Path("data")
    cities_dir: Path = Path("cities")
    scenarios_dir: Path = Path("scenarios")  # scenario files kept in the repository
    city: str = "bengaluru"
    database_url: str = "postgresql://glacies:glacies@localhost:5433/glacies"
    redis_url: str = "redis://localhost:6379/0"
    # A simulation is stopped after this long (Assumed): runs took 6-12 min on the dev laptop.
    simulation_timeout_s: int = 2700
    random_seed: int = 42

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def user_scenarios_dir(self) -> Path:
        """Scenarios made in the UI: outside ``processed/``, which clean builds delete."""
        return self.data_dir / "scenarios"

    @property
    def city_config_path(self) -> Path:
        return self.cities_dir / self.city / "city.toml"

    @property
    def demand_config_path(self) -> Path:
        return self.cities_dir / self.city / "demand.toml"

    @property
    def assignment_config_path(self) -> Path:
        return self.cities_dir / self.city / "assignment.toml"


def get_settings() -> Settings:
    return Settings()
