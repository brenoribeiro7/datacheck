from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from datacheck.core.settings import ApiSettings
from datacheck.infrastructure.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata is intentionally empty in DC-01. Establishing it here gives future
# product migrations one authoritative schema boundary without creating fake tables.
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
