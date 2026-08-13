import pytest
from pydantic import ValidationError

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

    settings = ApiSettings.from_environment()

    assert settings.environment == "test"
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")


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

    with pytest.raises(ValidationError):
        ApiSettings.from_environment()


def test_database_url_is_required_for_api(
    monkeypatch: pytest.MonkeyPatch,
    clear_datacheck_environment: None,
) -> None:
    monkeypatch.setenv("DATACHECK_ENVIRONMENT", "test")

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


def test_foundation_settings_do_not_include_future_security_or_staging_fields() -> None:
    assert set(ApiSettings.model_fields) == {"environment", "database_url"}
    assert set(WorkerSettings.model_fields) == {"environment", "celery_broker_url"}
