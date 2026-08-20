from collections.abc import Iterator

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from datacheck.core.settings import ApiSettings
from datacheck.infrastructure.database import DatabaseResources, create_database_resources


@pytest.fixture
def clear_datacheck_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove only DataCheck variables used by the backend foundation."""
    for variable in (
        "DATACHECK_ENVIRONMENT",
        "DATACHECK_DATABASE_URL",
        "DATACHECK_TRUSTED_ORIGINS",
        "DATACHECK_DATASET_STORAGE_ROOT",
        "DATACHECK_CELERY_BROKER_URL",
    ):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture(scope="module")
def identity_database() -> Iterator[DatabaseResources]:
    """Provide a migrated isolated database and restore a clean schema afterward."""
    settings = ApiSettings.from_environment()
    resources = create_database_resources(settings.database_url.get_secret_value())
    alembic_config = Config("alembic.ini")
    command.upgrade(alembic_config, "head")

    try:
        yield resources
    finally:
        command.downgrade(alembic_config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        resources.dispose()
