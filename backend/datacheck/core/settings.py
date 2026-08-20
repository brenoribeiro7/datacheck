import ipaddress
import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]
_HOST_LABEL_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def canonicalize_origin(value: str) -> str:
    """Validate and canonicalize one absolute HTTP(S) origin."""
    if not isinstance(value, str) or value != value.strip() or "*" in value:
        raise ValueError("trusted origin must be an explicit HTTP(S) origin")

    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("trusted origin must use HTTP or HTTPS")
    if not parsed.netloc or parsed.username is not None or parsed.password is not None:
        raise ValueError("trusted origin must not contain user information")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("trusted origin must not contain a path, query, or fragment")

    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("trusted origin must contain a hostname")
    hostname = hostname.lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if hostname != "localhost":
            labels = hostname.split(".")
            if (
                len(hostname) > 253
                or len(labels) < 2
                or any(_HOST_LABEL_PATTERN.fullmatch(label) is None for label in labels)
            ):
                raise ValueError("trusted origin hostname is invalid") from None
    else:
        hostname = address.compressed

    try:
        port = parsed.port
    except ValueError:
        raise ValueError("trusted origin port is invalid") from None
    if port == (80 if scheme == "http" else 443):
        port = None
    display_hostname = f"[{hostname}]" if ":" in hostname else hostname
    return f"{scheme}://{display_hostname}{f':{port}' if port is not None else ''}"


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
    trusted_origins: tuple[str, ...]

    @field_validator("trusted_origins")
    @classmethod
    def validate_trusted_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one trusted origin is required")
        canonical = tuple(canonicalize_origin(origin) for origin in value)
        if len(set(canonical)) != len(canonical):
            raise ValueError("trusted origins must be unique after canonicalization")
        return canonical

    @model_validator(mode="after")
    def validate_api_configuration(self) -> Self:
        if not self.database_url.get_secret_value().startswith("postgresql+psycopg://"):
            raise ValueError("database URL must use the postgresql+psycopg scheme")
        if self.environment == "production":
            if len(self.trusted_origins) != 1:
                raise ValueError("production requires exactly one trusted origin")
            if urlsplit(self.trusted_origins[0]).scheme != "https":
                raise ValueError("production trusted origin must use HTTPS")
        else:
            for origin in self.trusted_origins:
                parsed = urlsplit(origin)
                if parsed.scheme != "http":
                    continue
                hostname = parsed.hostname
                if hostname == "localhost":
                    continue
                try:
                    if hostname is not None and ipaddress.ip_address(hostname).is_loopback:
                        continue
                except ValueError:
                    pass
                raise ValueError("development HTTP origins must use a loopback hostname")
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
