import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import DateTime, Engine, delete, func, insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from datacheck.core.settings import ApiSettings
from datacheck.identity.models import User, UserSession
from datacheck.infrastructure.database import create_database_resources

pytestmark = pytest.mark.integration


def _alembic_config() -> Config:
    return Config("alembic.ini")


def _user_values(*, user_id: uuid.UUID, local_part: str) -> dict[str, Any]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "id": user_id,
        "email": f"{local_part}@example.test",
        "email_normalized": f"{local_part.lower()}@example.test",
        "password_hash": "$argon2id$synthetic-fixture",
        "created_at": now,
        "updated_at": now,
    }


def _session_values(
    *,
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    token_byte: int,
) -> dict[str, Any]:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return {
        "id": session_id,
        "user_id": user_id,
        "token_hash": bytes([token_byte]) * 32,
        "csrf_token": bytes([token_byte + 1]) * 32,
        "created_at": created_at,
        "last_seen_at": created_at,
        "absolute_expires_at": created_at + timedelta(hours=12),
        "revoked_at": None,
    }


def _assert_constraint_rejects(
    engine: Engine,
    values: Mapping[str, Any],
    constraint_name: str,
) -> None:
    with pytest.raises(IntegrityError) as error, engine.begin() as connection:
        connection.execute(insert(UserSession).values(**values))

    assert constraint_name in str(error.value.orig)


def _assert_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {"alembic_version", "sessions", "users"}.issubset(inspector.get_table_names())

    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert set(user_columns) == {
        "id",
        "email",
        "email_normalized",
        "password_hash",
        "created_at",
        "updated_at",
    }
    assert str(user_columns["id"]["type"]) == "UUID"
    assert str(user_columns["email"]["type"]) == "VARCHAR(254)"
    assert str(user_columns["email_normalized"]["type"]) == "VARCHAR(254)"
    assert str(user_columns["password_hash"]["type"]) == "TEXT"
    assert str(user_columns["created_at"]["type"]) == "TIMESTAMP"
    assert isinstance(user_columns["created_at"]["type"], DateTime)
    assert user_columns["created_at"]["type"].timezone is True
    assert all(column["nullable"] is False for column in user_columns.values())
    assert inspector.get_pk_constraint("users") == {
        "constrained_columns": ["id"],
        "name": "pk_users",
        "comment": None,
        "dialect_options": {"postgresql_include": []},
    }
    assert {item["name"] for item in inspector.get_unique_constraints("users")} == {
        "uq_users_email_normalized"
    }
    assert {item["name"] for item in inspector.get_check_constraints("users")} == {
        "ck_users_email_normalized_lowercase",
        "ck_users_email_normalized_octet_length",
        "ck_users_email_octet_length",
        "ck_users_updated_not_before_created",
    }

    session_columns = {column["name"]: column for column in inspector.get_columns("sessions")}
    assert set(session_columns) == {
        "id",
        "user_id",
        "token_hash",
        "csrf_token",
        "created_at",
        "last_seen_at",
        "absolute_expires_at",
        "revoked_at",
    }
    assert {str(session_columns[name]["type"]) for name in ("id", "user_id")} == {"UUID"}
    assert str(session_columns["token_hash"]["type"]) == "BYTEA"
    assert str(session_columns["csrf_token"]["type"]) == "BYTEA"
    assert session_columns["revoked_at"]["nullable"] is True
    assert all(
        column["nullable"] is False
        for name, column in session_columns.items()
        if name != "revoked_at"
    )
    assert {item["name"] for item in inspector.get_unique_constraints("sessions")} == {
        "uq_sessions_token_hash"
    }
    assert {item["name"] for item in inspector.get_check_constraints("sessions")} == {
        "ck_sessions_absolute_lifetime",
        "ck_sessions_csrf_token_length",
        "ck_sessions_last_seen_not_after_absolute_expiry",
        "ck_sessions_last_seen_not_before_created",
        "ck_sessions_revoked_not_before_created",
        "ck_sessions_token_hash_length",
    }
    foreign_keys = inspector.get_foreign_keys("sessions")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["name"] == "fk_sessions_user_id_users"
    assert foreign_keys[0]["constrained_columns"] == ["user_id"]
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["referred_columns"] == ["id"]
    assert foreign_keys[0]["options"] == {"ondelete": "CASCADE"}

    indexes = {item["name"]: item for item in inspector.get_indexes("sessions")}
    assert {
        "ix_sessions_absolute_expires_at",
        "ix_sessions_last_seen_at",
        "ix_sessions_revoked_at",
        "ix_sessions_user_id",
    }.issubset(indexes)
    revoked_where = str(indexes["ix_sessions_revoked_at"]["dialect_options"]["postgresql_where"])
    assert "revoked_at IS NOT NULL" in revoked_where


def _assert_constraint_behavior(engine: Engine) -> None:
    user_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(insert(User).values(**_user_values(user_id=user_id, local_part="Alpha")))

    duplicate_user = _user_values(user_id=uuid.uuid4(), local_part="alpha")
    with pytest.raises(IntegrityError) as duplicate_email, engine.begin() as connection:
        connection.execute(insert(User).values(**duplicate_user))
    assert "uq_users_email_normalized" in str(duplicate_email.value.orig)

    valid_session = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=1)
    with engine.begin() as connection:
        connection.execute(insert(UserSession).values(**valid_session))

    duplicate_token = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=1)
    with pytest.raises(IntegrityError) as duplicate_hash, engine.begin() as connection:
        connection.execute(insert(UserSession).values(**duplicate_token))
    assert "uq_sessions_token_hash" in str(duplicate_hash.value.orig)

    invalid_token = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=2)
    invalid_token["token_hash"] = b"short"
    _assert_constraint_rejects(engine, invalid_token, "ck_sessions_token_hash_length")

    invalid_csrf = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=3)
    invalid_csrf["csrf_token"] = b"short"
    _assert_constraint_rejects(engine, invalid_csrf, "ck_sessions_csrf_token_length")

    before_created = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=4)
    before_created["last_seen_at"] = before_created["created_at"] - timedelta(seconds=1)
    _assert_constraint_rejects(engine, before_created, "ck_sessions_last_seen_not_before_created")

    after_expiry = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=5)
    after_expiry["last_seen_at"] = after_expiry["absolute_expires_at"] + timedelta(seconds=1)
    _assert_constraint_rejects(
        engine, after_expiry, "ck_sessions_last_seen_not_after_absolute_expiry"
    )

    wrong_lifetime = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=6)
    wrong_lifetime["absolute_expires_at"] = wrong_lifetime["created_at"] + timedelta(hours=11)
    _assert_constraint_rejects(engine, wrong_lifetime, "ck_sessions_absolute_lifetime")

    early_revocation = _session_values(session_id=uuid.uuid4(), user_id=user_id, token_byte=7)
    early_revocation["revoked_at"] = early_revocation["created_at"] - timedelta(seconds=1)
    _assert_constraint_rejects(engine, early_revocation, "ck_sessions_revoked_not_before_created")

    invalid_fk = _session_values(session_id=uuid.uuid4(), user_id=uuid.uuid4(), token_byte=8)
    with pytest.raises(IntegrityError) as foreign_key, engine.begin() as connection:
        connection.execute(insert(UserSession).values(**invalid_fk))
    assert "fk_sessions_user_id_users" in str(foreign_key.value.orig)

    cascade_user_id = uuid.uuid4()
    cascade_session_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(User).values(**_user_values(user_id=cascade_user_id, local_part="Cascade"))
        )
        connection.execute(
            insert(UserSession).values(
                **_session_values(
                    session_id=cascade_session_id,
                    user_id=cascade_user_id,
                    token_byte=9,
                )
            )
        )
        connection.execute(delete(User).where(User.id == cascade_user_id))
        remaining = connection.scalar(
            select(func.count())
            .select_from(UserSession)
            .where(UserSession.id == cascade_session_id)
        )
    assert remaining == 0


def test_model_import_only_declares_metadata() -> None:
    environment = os.environ.copy()
    environment["DATACHECK_DATABASE_URL"] = (
        "postgresql+psycopg://invalid:invalid@127.0.0.1:1/invalid"
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from datacheck.identity.models import Base; print(','.join(sorted(Base.metadata.tables)))",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.stdout.strip() == "sessions,users"


def test_identity_migration_schema_constraints_and_cycle() -> None:
    settings = ApiSettings.from_environment()
    resources = create_database_resources(settings.database_url.get_secret_value())
    alembic_config = _alembic_config()

    try:
        # The integration suite may follow an explicit manual migration audit. Resetting
        # only this isolated database keeps both the migration cycle and legacy clean-DB
        # readiness test deterministic without changing shared test infrastructure.
        command.downgrade(alembic_config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        assert inspect(resources.engine).get_table_names() == []
        command.heads(alembic_config)

        command.upgrade(alembic_config, "head")
        _assert_schema(resources.engine)
        command.check(alembic_config)

        command.downgrade(alembic_config, "base")
        assert set(inspect(resources.engine).get_table_names()) == {"alembic_version"}

        command.upgrade(alembic_config, "head")
        _assert_schema(resources.engine)
        _assert_constraint_behavior(resources.engine)
    finally:
        command.downgrade(alembic_config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        resources.dispose()
