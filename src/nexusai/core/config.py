from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    database_url: SecretStr | None = None
    analytics_database_url: SecretStr | None = None
    data_dir: Path = Path("data")
    model_dir: Path = Path("artifacts/embedding")

    @field_validator("database_url", "analytics_database_url", mode="before")
    @classmethod
    def empty_means_unconfigured(cls, value):
        return None if value == "" else value

    @field_validator("database_url", "analytics_database_url")
    @classmethod
    def validate_database(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            try:
                url = make_url(value.get_secret_value())
                valid = url.drivername == "postgresql+psycopg" and bool(url.host and url.database)
            except (ArgumentError, TypeError, ValueError):
                valid = False
            if not valid:
                raise ValueError("Use a PostgreSQL URL with the psycopg driver, host and database")
        return value
