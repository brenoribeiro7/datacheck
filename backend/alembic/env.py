from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from datacheck.analysis import models as analysis_models
from datacheck.core.settings import ApiSettings
from datacheck.datasets import models as dataset_models
from datacheck.identity import models as identity_models
from datacheck.infrastructure.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importing the concrete mappings registers their tables on the authoritative metadata
# without opening a database connection or loading runtime settings.
_identity_tables = (identity_models.User.__table__, identity_models.UserSession.__table__)
_dataset_tables = (dataset_models.Dataset.__table__, dataset_models.ValidationRule.__table__)
_analysis_tables = (
    analysis_models.Analysis.__table__,
    analysis_models.ValidationResult.__table__,
)
target_metadata = Base.metadata


def get_database_url() -> str:
    """Resolve the migration URL from the same environment contract as the API."""
    return ApiSettings.from_environment().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Render migrations without creating an Engine."""
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the database selected by DataCheck settings."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
