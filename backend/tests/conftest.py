import pytest


@pytest.fixture
def clear_datacheck_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove only DataCheck variables used by the backend foundation."""
    for variable in (
        "DATACHECK_ENVIRONMENT",
        "DATACHECK_DATABASE_URL",
        "DATACHECK_CELERY_BROKER_URL",
    ):
        monkeypatch.delenv(variable, raising=False)
