from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class EnvironmentSettings(BaseSettings):
    """Settings shared by DataCheck processes, sourced only from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="DATACHECK_",
        case_sensitive=False,
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Environment

    @classmethod
    def from_environment(cls) -> Self:
        """Load a concrete process configuration from environment variables."""
        # BaseSettings supplies required fields from environment sources at runtime;
        # its generated static constructor cannot express that no-argument path.
        return cls()  # type: ignore[call-arg]


class ApiSettings(EnvironmentSettings):
    """Configuration required to start the API process."""

    database_url: SecretStr

    @model_validator(mode="after")
    def validate_database_driver(self) -> Self:
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("database URL must use the postgresql+psycopg scheme")
        return self


class WorkerSettings(EnvironmentSettings):
    """Configuration required to start the Celery worker process."""

    celery_broker_url: SecretStr

    @model_validator(mode="after")
    def validate_broker_scheme(self) -> Self:
        scheme = urlsplit(self.celery_broker_url.get_secret_value()).scheme
        if scheme not in {"redis", "rediss"}:
            raise ValueError("Celery broker URL must use the redis or rediss scheme")
        return self
