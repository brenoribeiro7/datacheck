import uuid
from datetime import UTC, datetime

import pytest
from alembic.config import Config
from sqlalchemy import Engine, delete, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from datacheck.core.settings import ApiSettings
from datacheck.datasets.models import Dataset, ValidationRule
from datacheck.identity.models import User
from datacheck.infrastructure.database import create_database_resources

pytestmark = pytest.mark.integration


def _alembic_config() -> Config:
    return Config("alembic.ini")


def _assert_dc03_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "datasets",
        "sessions",
        "users",
        "validation_rules",
    }

    dataset_columns = {column["name"]: column for column in inspector.get_columns("datasets")}
    assert set(dataset_columns) == {
        "id",
        "owner_id",
        "name",
        "original_filename",
        "storage_key",
        "content_sha256",
        "size_bytes",
        "row_count",
        "column_names",
        "uploaded_at",
        "created_at",
        "updated_at",
    }
    assert all(
        dataset_columns[name]["nullable"] is False
        for name in ("id", "owner_id", "name", "created_at", "updated_at")
    )
    assert all(
        dataset_columns[name]["nullable"] is True
        for name in (
            "original_filename",
            "storage_key",
            "content_sha256",
            "size_bytes",
            "row_count",
            "column_names",
            "uploaded_at",
        )
    )
    assert {item["name"] for item in inspector.get_unique_constraints("datasets")} == {
        "uq_datasets_storage_key"
    }
    assert {item["name"] for item in inspector.get_check_constraints("datasets")} == {
        "ck_datasets_column_names",
        "ck_datasets_content_sha256_length",
        "ck_datasets_name",
        "ck_datasets_original_filename",
        "ck_datasets_row_count",
        "ck_datasets_size_bytes",
        "ck_datasets_storage_key_format",
        "ck_datasets_updated_not_before_created",
        "ck_datasets_upload_metadata_all_or_none",
        "ck_datasets_upload_timestamps",
    }
    dataset_fks = inspector.get_foreign_keys("datasets")
    assert len(dataset_fks) == 1
    assert dataset_fks[0]["name"] == "fk_datasets_owner_id_users"
    assert dataset_fks[0]["options"] == {"ondelete": "CASCADE"}
    assert "ix_datasets_owner_created_id" in {
        item["name"] for item in inspector.get_indexes("datasets")
    }

    rule_columns = {column["name"]: column for column in inspector.get_columns("validation_rules")}
    assert set(rule_columns) == {
        "id",
        "dataset_id",
        "rule_type",
        "target_column",
        "configuration",
        "created_at",
    }
    assert all(column["nullable"] is False for column in rule_columns.values())
    assert {item["name"] for item in inspector.get_unique_constraints("validation_rules")} == {
        "uq_validation_rules_definition"
    }
    assert {item["name"] for item in inspector.get_check_constraints("validation_rules")} == {
        "ck_validation_rules_configuration_object",
        "ck_validation_rules_target_column",
        "ck_validation_rules_type",
    }
    rule_fks = inspector.get_foreign_keys("validation_rules")
    assert len(rule_fks) == 1
    assert rule_fks[0]["name"] == "fk_validation_rules_dataset_id_datasets"
    assert rule_fks[0]["options"] == {"ondelete": "CASCADE"}
    assert "ix_validation_rules_dataset_created_id" in {
        item["name"] for item in inspector.get_indexes("validation_rules")
    }


def _assert_database_constraints(engine: Engine) -> None:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    user = User(
        id=user_id,
        email="migration@example.test",
        email_normalized="migration@example.test",
        password_hash="$argon2id$fixture",
        created_at=now,
        updated_at=now,
    )
    dataset = Dataset(
        id=dataset_id,
        owner_id=user_id,
        name="Migration dataset",
        created_at=now,
        updated_at=now,
    )
    rule = ValidationRule(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        rule_type="required",
        target_column="id",
        configuration={},
        created_at=now,
    )
    with Session(engine) as session, session.begin():
        session.add(user)
        session.flush()
        session.add(dataset)
        session.flush()
        session.add(rule)

    duplicate = ValidationRule(
        id=uuid.uuid4(),
        dataset_id=dataset_id,
        rule_type="required",
        target_column="id",
        configuration={},
        created_at=now,
    )
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(duplicate)

    with Session(engine) as session, session.begin():
        session.execute(delete(User).where(User.id == user_id))
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM datasets")) == 0
        assert connection.scalar(text("SELECT count(*) FROM validation_rules")) == 0


def test_dc03_migration_schema_constraints_and_full_cycle() -> None:
    settings = ApiSettings.from_environment()
    resources = create_database_resources(settings.database_url.get_secret_value())
    alembic_config = _alembic_config()

    try:
        command.downgrade(alembic_config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        assert inspect(resources.engine).get_table_names() == []
        command.heads(alembic_config)

        command.upgrade(alembic_config, "0001_identity_sessions")
        assert set(inspect(resources.engine).get_table_names()) == {
            "alembic_version",
            "sessions",
            "users",
        }
        command.upgrade(alembic_config, "head")
        _assert_dc03_schema(resources.engine)
        command.check(alembic_config)
        _assert_database_constraints(resources.engine)

        command.downgrade(alembic_config, "0001_identity_sessions")
        assert set(inspect(resources.engine).get_table_names()) == {
            "alembic_version",
            "sessions",
            "users",
        }
        command.downgrade(alembic_config, "base")
        assert set(inspect(resources.engine).get_table_names()) == {"alembic_version"}

        command.upgrade(alembic_config, "head")
        _assert_dc03_schema(resources.engine)
    finally:
        command.downgrade(alembic_config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        resources.dispose()
