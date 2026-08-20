import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from alembic.config import Config
from sqlalchemy import Engine, delete, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from datacheck.analysis.models import Analysis, ValidationResult
from datacheck.core.settings import ApiSettings
from datacheck.datasets.models import Dataset
from datacheck.identity.models import User
from datacheck.infrastructure.database import DatabaseResources, create_database_resources

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 8, 3, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_analysis_migration_rows(identity_database: DatabaseResources) -> None:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(User))


def _config() -> Config:
    return Config("alembic.ini")


def _assert_dc05_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "analyses",
        "datasets",
        "sessions",
        "users",
        "validation_results",
        "validation_rules",
    }
    analysis_columns = {column["name"]: column for column in inspector.get_columns("analyses")}
    assert set(analysis_columns) == {
        "id",
        "dataset_id",
        "source_original_filename",
        "source_content_sha256",
        "source_size_bytes",
        "source_row_count",
        "source_column_names",
        "source_uploaded_at",
        "total_violation_count",
        "quality_score",
        "created_at",
    }
    assert analysis_columns["quality_score"]["nullable"] is True
    assert all(
        column["nullable"] is False
        for name, column in analysis_columns.items()
        if name != "quality_score"
    )
    assert {item["name"] for item in inspector.get_check_constraints("analyses")} == {
        "ck_analyses_quality_score",
        "ck_analyses_source_column_names",
        "ck_analyses_source_content_sha256_length",
        "ck_analyses_source_row_count",
        "ck_analyses_source_size_bytes",
        "ck_analyses_total_violation_count",
    }
    analysis_fks = inspector.get_foreign_keys("analyses")
    assert len(analysis_fks) == 1
    assert analysis_fks[0]["name"] == "fk_analyses_dataset_id_datasets"
    assert analysis_fks[0]["options"] == {"ondelete": "CASCADE"}
    assert "ix_analyses_dataset_created_id" in {
        item["name"] for item in inspector.get_indexes("analyses")
    }

    result_columns = {
        column["name"]: column for column in inspector.get_columns("validation_results")
    }
    assert set(result_columns) == {
        "analysis_id",
        "rule_position",
        "source_rule_id",
        "rule_type",
        "target_column",
        "configuration",
        "evaluated_count",
        "passed_count",
        "violation_count",
        "skipped_count",
        "violation_samples",
    }
    assert all(column["nullable"] is False for column in result_columns.values())
    assert inspector.get_pk_constraint("validation_results")["constrained_columns"] == [
        "analysis_id",
        "rule_position",
    ]
    assert {item["name"] for item in inspector.get_unique_constraints("validation_results")} == {
        "uq_validation_results_analysis_source_rule"
    }
    assert {item["name"] for item in inspector.get_check_constraints("validation_results")} == {
        "ck_validation_results_configuration_object",
        "ck_validation_results_count_balance",
        "ck_validation_results_nonnegative_counts",
        "ck_validation_results_rule_position",
        "ck_validation_results_rule_type",
        "ck_validation_results_target_column",
        "ck_validation_results_violation_samples",
    }
    result_fks = inspector.get_foreign_keys("validation_results")
    assert len(result_fks) == 1
    assert result_fks[0]["name"] == "fk_validation_results_analysis_id_analyses"
    assert result_fks[0]["options"] == {"ondelete": "CASCADE"}
    assert result_fks[0]["referred_table"] == "analyses"


def _insert_parent_rows(engine: Engine) -> tuple[uuid.UUID, uuid.UUID]:
    user_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            User(
                id=user_id,
                email="analysis-migration@example.test",
                email_normalized="analysis-migration@example.test",
                password_hash="$argon2id$fixture",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.flush()
        session.add(
            Dataset(
                id=dataset_id,
                owner_id=user_id,
                name="Migration analysis",
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
    return user_id, dataset_id


def _analysis(dataset_id: uuid.UUID, **overrides: object) -> Analysis:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "dataset_id": dataset_id,
        "source_original_filename": "source.csv",
        "source_content_sha256": b"x" * 32,
        "source_size_bytes": 10,
        "source_row_count": 1,
        "source_column_names": ["value"],
        "source_uploaded_at": _NOW,
        "total_violation_count": 0,
        "quality_score": Decimal("100.00"),
        "created_at": _NOW,
    }
    values.update(overrides)
    return Analysis(**values)


def _result(analysis_id: uuid.UUID, **overrides: object) -> ValidationResult:
    values: dict[str, object] = {
        "analysis_id": analysis_id,
        "rule_position": 0,
        "source_rule_id": uuid.uuid4(),
        "rule_type": "required",
        "target_column": "value",
        "configuration": {},
        "evaluated_count": 1,
        "passed_count": 1,
        "violation_count": 0,
        "skipped_count": 0,
        "violation_samples": [],
    }
    values.update(overrides)
    return ValidationResult(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_content_sha256", b"short"),
        ("source_size_bytes", 0),
        ("source_size_bytes", 10_485_761),
        ("source_row_count", -1),
        ("source_column_names", {}),
        ("source_column_names", []),
        ("total_violation_count", -1),
        ("quality_score", Decimal("-0.01")),
        ("quality_score", Decimal("100.01")),
    ],
)
def test_analysis_constraints_reject_invalid_rows(
    identity_database: DatabaseResources,
    field: str,
    value: object,
) -> None:
    engine = identity_database.engine
    _user_id, dataset_id = _insert_parent_rows(engine)
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(_analysis(dataset_id, **{field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"rule_position": -1},
        {"rule_type": "custom"},
        {"configuration": []},
        {"evaluated_count": -1},
        {"passed_count": 0, "violation_count": 0, "evaluated_count": 1},
        {"violation_samples": [{} for _ in range(21)]},
    ],
)
def test_validation_result_constraints_reject_invalid_rows(
    identity_database: DatabaseResources,
    overrides: dict[str, object],
) -> None:
    engine = identity_database.engine
    _user_id, dataset_id = _insert_parent_rows(engine)
    analysis = _analysis(dataset_id)
    analysis_id = analysis.id
    with Session(engine) as session, session.begin():
        session.add(analysis)
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(_result(analysis_id, **overrides))


def test_validation_result_composite_key_and_rule_snapshot_are_unique_per_analysis(
    identity_database: DatabaseResources,
) -> None:
    engine = identity_database.engine
    _user_id, dataset_id = _insert_parent_rows(engine)
    analysis = _analysis(dataset_id)
    analysis_id = analysis.id
    first = _result(analysis_id)
    source_rule_id = first.source_rule_id
    with Session(engine) as session, session.begin():
        session.add(analysis)
        session.add(first)

    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(_result(analysis_id, rule_position=0))
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(
            _result(
                analysis_id,
                rule_position=1,
                source_rule_id=source_rule_id,
            )
        )


def test_analysis_migration_full_cycle_and_cascades() -> None:
    settings = ApiSettings.from_environment()
    resources = create_database_resources(settings.database_url.get_secret_value())
    config = _config()
    try:
        command.downgrade(config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        assert inspect(resources.engine).get_table_names() == []

        command.upgrade(config, "0001_identity_sessions")
        command.upgrade(config, "0002_datasets_rules_csv")
        command.upgrade(config, "0003_analysis_results_score")
        _assert_dc05_schema(resources.engine)
        command.heads(config)
        command.check(config)

        user_id, dataset_id = _insert_parent_rows(resources.engine)
        analysis = _analysis(dataset_id)
        result = _result(analysis.id)
        with Session(resources.engine) as session, session.begin():
            session.add(analysis)
            session.add(result)
        with resources.engine.begin() as connection:
            connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            assert connection.scalar(text("SELECT count(*) FROM analyses")) == 0
            assert connection.scalar(text("SELECT count(*) FROM validation_results")) == 0

        _insert_parent_rows(resources.engine)
        command.downgrade(config, "0002_datasets_rules_csv")
        assert set(inspect(resources.engine).get_table_names()) == {
            "alembic_version",
            "datasets",
            "sessions",
            "users",
            "validation_rules",
        }
        command.upgrade(config, "head")
        _assert_dc05_schema(resources.engine)
    finally:
        command.downgrade(config, "base")
        with resources.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        resources.dispose()
