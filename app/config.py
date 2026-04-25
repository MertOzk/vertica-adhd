"""Environment-driven configuration. One source of truth."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM router
    vertica_router_url: str = "http://vertica-router:8080"
    vertica_router_api_key: str = "changeme"
    default_model: str = "claude-sonnet-4-6"

    # Home Assistant
    ha_url: str = "http://homeassistant:8123"
    ha_token: str = ""
    ha_notify_target: str = ""

    # Exposure
    public_url: str = "https://vertica.tailnet.ts.net"

    # User defaults (used to seed the single user row on first boot)
    user_name: str = "Mert"
    user_timezone: str = "America/Los_Angeles"
    morning_cron: str = "0 9 * * *"
    evening_cron: str = "0 21 * * *"

    # Paths
    data_dir: Path = Field(default=Path("/data"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vertica-adhd.db"

    @property
    def brain_dir(self) -> Path:
        return self.data_dir / "brain"

    @property
    def daily_dir(self) -> Path:
        return self.brain_dir / "daily"

    @property
    def coach_manual_path(self) -> Path:
        return self.brain_dir / "COACH.md"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"


settings = Settings()
