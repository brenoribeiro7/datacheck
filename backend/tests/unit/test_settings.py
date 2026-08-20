import pytest
from pydantic import SecretStr, ValidationError

from datacheck.core.settings import ApiSettings, WorkerSettings


def test_api_settings_load_valid_environment(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")
    monkeypatch.setenv(
        "DATACHECK_DATABASE_URL",
        "postgresql+psycopg://127.0.0.1/datacheck",
    )
    monkeypatch.setenv(
        "DATACHECK_TRUSTED_ORIGINS",
        '["http://LOCALHOST:80", "https://Example.TEST:443"]',
    )

    settings = ApiSettings.from_environment()

    assert settings.environment == "test"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    assert settings.trusted_origins == ("http://localhost", "https://example.test")


def test_worker_settings_load_valid_environment(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "production")
    monkeypatch.setenv("DATACHECK_CELERY_BROKER_URL", "rediss://redis.example.invalid/0")

    settings = WorkerSettings.from_environment()

    assert settings.environment == "production"
    assert settings.celery_broker_url.get_secret_value().startswith("rediss://")


def test_invalid_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "staging")
    monkeypatch.setenv(
        "DATACHECK_DATABASE_URL",
        "postgresql+psycopg://127.0.0.1/datacheck",
    )
    monkeypatch.setenv("DATACHECK_TRUSTED_ORIGINS", '["http://localhost:3000"]')

    with pytest.raises(ValidationError):
        ApiSettings.from_environment()


def test_database_url_is_required_for_api(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")
    monkeypatch.setenv("DATACHECK_TRUSTED_ORIGINS", '["http://localhost:3000"]')

    with pytest.raises(ValidationError):
        ApiSettings.from_environment()


def test_broker_url_is_required_for_worker(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")

    with pytest.raises(ValidationError):
        WorkerSettings.from_environment()


def test_api_rejects_a_non_psycopg_database_url(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")
    monkeypatch.setenv("DATACHECK_DATABASE_URL", "postgresql://127.0.0.1/datacheck")
    monkeypatch.setenv("DATACHECK_TRUSTED_ORIGINS", '["http://localhost:3000"]')

    with pytest.raises(ValidationError):
        ApiSettings.from_environment()


def test_worker_rejects_a_non_redis_broker(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")
    monkeypatch.setenv("DATACHECK_CELERY_BROKER_URL", "amqp://broker.example.invalid")

    with pytest.raises(ValidationError):
        WorkerSettings.from_environment()


def test_api_settings_require_trusted_origins(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")
    monkeypatch.setenv(
        "DATACHECK_DATABASE_URL",
        "postgresql+psycopg://127.0.0.1/datacheck",
    )

    with pytest.raises(ValidationError):
        ApiSettings.from_environment()


@pytest.mark.parametrize(
    "origins",
    [
        (),
        ("*",),
        ("null",),
        ("http://localhost", "http://LOCALHOST:80"),
        ("https://example.test/path",),
        ("https://example.test?query=value",),
        ("https://example.test#fragment",),
        ("https://user@example.test",),
        ("https://*.example.test",),
        ("https://example[.]test",),
    ],
)
def test_api_settings_reject_invalid_or_duplicate_origins(origins: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        ApiSettings(
            environment="test",
            database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
            trusted_origins=origins,
        )


def test_production_requires_one_https_origin() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(
            environment="production",
            database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
            trusted_origins=("http://localhost",),
        )
    with pytest.raises(ValidationError):
        ApiSettings(
            environment="production",
            database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
            trusted_origins=("https://one.example.test", "https://two.example.test"),
        )

    settings = ApiSettings(
        environment="production",
        database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
        trusted_origins=("https://APP.EXAMPLE.TEST:443",),
    )

    assert settings.trusted_origins == ("https://app.example.test",)


def test_non_production_http_is_limited_to_loopback() -> None:
    settings = ApiSettings(
        environment="development",
        database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
        trusted_origins=("http://localhost:3000", "http://127.0.0.1:5173"),
    )
    assert settings.trusted_origins == (
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    )

    with pytest.raises(ValidationError):
        ApiSettings(
            environment="test",
            database_url=SecretStr("postgresql+psycopg://127.0.0.1/datacheck"),
            trusted_origins=("http://app.example.test",),
        )


def test_settings_security_fields_remain_process_specific() -> None:
    assert set(ApiSettings.model_fields) == {"environment", "database_url", "trusted_origins"}
    assert set(WorkerSettings.model_fields) == {"environment", "celery_broker_url"}
