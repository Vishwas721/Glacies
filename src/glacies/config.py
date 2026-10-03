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
    city: str = "bengaluru"
    database_url: str = "postgresql://glacies:glacies@localhost:5432/glacies"
    redis_url: str = "redis://localhost:6379/0"
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
    def city_config_path(self) -> Path:
        return self.cities_dir / self.city / "city.toml"


def get_settings() -> Settings:
    return Settings()
