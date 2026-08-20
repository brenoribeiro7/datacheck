import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, update

from datacheck.analysis.adapters import AnalysisDataIntegrityError
from datacheck.analysis.models import Analysis, ValidationResult
from datacheck.analysis.repositories import ValidationResultRepository
from datacheck.analysis.service import AnalysisRequiresRules, AnalysisService
from datacheck.datasets.models import Dataset, ValidationRule
from datacheck.datasets.service import DatasetNotReady, DatasetService
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.identity.models import User
from datacheck.infrastructure.database import DatabaseResources

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_analysis_service_rows(identity_database: DatabaseResources) -> None:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(User))


def _insert_user(resources: DatabaseResources, key: str) -> uuid.UUID:
    user_id = uuid.uuid4()
    with resources.session_factory() as session, session.begin():
        session.add(
            User(
                id=user_id,
                email=f"{key}@example.test",
                email_normalized=f"{key}@example.test",
                password_hash="$argon2id$fixture",
                created_at=_NOW - timedelta(days=1),
                updated_at=_NOW - timedelta(days=1),
            )
        )
    return user_id


def _services(
    resources: DatabaseResources, root: Path
) -> tuple[DatasetService, AnalysisService, LocalDatasetStorage]:
    storage = LocalDatasetStorage(root)
    return (
        DatasetService(
            session_factory=resources.session_factory,
            storage=storage,
            clock=lambda: _NOW,
        ),
        AnalysisService(
            session_factory=resources.session_factory,
            storage=storage,
        ),
        storage,
    )


def _ready_dataset(
    resources: DatabaseResources,
    root: Path,
    *,
    key: str = "analysis",
) -> tuple[uuid.UUID, uuid.UUID, DatasetService, AnalysisService, LocalDatasetStorage]:
    owner_id = _insert_user(resources, key)
    datasets, analyses, storage = _services(resources, root)
    dataset = datasets.create_dataset(owner_id=owner_id, name="Analysis dataset")
    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="people.csv",
        source=BytesIO(b"id,email,age\n1,a@example.test,10\n1,bad,200\n,c@example.test,x\n"),
    )
    rule_definitions: tuple[tuple[str, str, dict[str, object]], ...] = (
        ("required", "id", {}),
        ("unique", "id", {}),
        ("type", "age", {"expected_type": "integer"}),
        ("range", "age", {"minimum": 0.0, "maximum": 100.0}),
        ("regex", "email", {"pattern": "^[^@]+@[^@]+$"}),
    )
    for rule_type, column, configuration in rule_definitions:
        datasets.create_rule(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            rule_type=rule_type,
            target_column=column,
            configuration=configuration,
        )
    return owner_id, dataset.dataset_id, datasets, analyses, storage


def test_analysis_service_runs_real_engine_and_persists_complete_snapshot(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, _datasets, service, _storage = _ready_dataset(
        identity_database, tmp_path / "storage"
    )

    detail = service.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    assert detail.dataset_id == dataset_id
    assert detail.source.original_filename == "people.csv"
    assert detail.source.row_count == 3
    assert detail.source.column_names == ("id", "email", "age")
    assert detail.quality_score == Decimal("57.14")
    assert detail.total_violation_count == 6
    assert len(detail.rule_results) == 5
    assert [result.rule_position for result in detail.rule_results] == list(range(5))
    by_type = {result.rule_type: result for result in detail.rule_results}
    assert by_type["required"].violation_samples[0].row_number == 3
    assert by_type["unique"].violation_samples[0].row_number == 2
    assert by_type["range"].configuration == {"minimum": 0.0, "maximum": 100.0}

    persisted = service.get_analysis(
        owner_id=owner_id,
        dataset_id=dataset_id,
        analysis_id=detail.analysis_id,
    )
    assert persisted == detail
    summaries = service.list_analyses(owner_id=owner_id, dataset_id=dataset_id, limit=50, offset=0)
    assert [summary.analysis_id for summary in summaries] == [detail.analysis_id]
    assert summaries[0].quality_score == detail.quality_score


def test_analysis_requires_upload_and_at_least_one_rule(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "guardrails")
    datasets, analyses, _storage = _services(identity_database, tmp_path / "storage")
    dataset = datasets.create_dataset(owner_id=owner_id, name="Guardrails")

    with pytest.raises(DatasetNotReady):
        analyses.create_analysis(owner_id=owner_id, dataset_id=dataset.dataset_id)

    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="empty-rules.csv",
        source=BytesIO(b"id\n1\n"),
    )
    with pytest.raises(AnalysisRequiresRules):
        analyses.create_analysis(owner_id=owner_id, dataset_id=dataset.dataset_id)

    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 0


def test_header_only_analysis_persists_null_score_and_zero_counts(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "header-only")
    datasets, analyses, _storage = _services(identity_database, tmp_path / "storage")
    dataset = datasets.create_dataset(owner_id=owner_id, name="Header only")
    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="header.csv",
        source=BytesIO(b"id\n"),
    )
    datasets.create_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_type="required",
        target_column="id",
        configuration={},
    )

    detail = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset.dataset_id)

    assert detail.source.row_count == 0
    assert detail.quality_score is None
    assert detail.total_violation_count == 0
    assert detail.rule_results[0].evaluated_count == 0
    assert detail.rule_results[0].violation_samples == ()


def test_analysis_persists_complete_counts_with_only_twenty_samples(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "bounded-samples")
    datasets, analyses, _storage = _services(identity_database, tmp_path / "storage")
    dataset = datasets.create_dataset(owner_id=owner_id, name="Bounded samples")
    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="empty-values.csv",
        source=BytesIO(b"value\n" + b'""\n' * 25),
    )
    datasets.create_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_type="required",
        target_column="value",
        configuration={},
    )

    detail = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset.dataset_id)

    result = detail.rule_results[0]
    assert result.evaluated_count == 25
    assert result.violation_count == 25
    assert len(result.violation_samples) == 20
    assert [sample.row_number for sample in result.violation_samples] == list(range(1, 21))


@pytest.mark.parametrize("corruption", ["missing", "size", "hash", "rows", "columns"])
def test_analysis_rejects_missing_or_inconsistent_active_source_without_history(
    identity_database: DatabaseResources,
    tmp_path: Path,
    corruption: str,
) -> None:
    owner_id, dataset_id, _datasets, analyses, storage = _ready_dataset(
        identity_database, tmp_path / corruption, key=f"corrupt-{corruption}"
    )
    with identity_database.session_factory() as session, session.begin():
        dataset = session.get(Dataset, dataset_id)
        assert dataset is not None and dataset.storage_key is not None
        if corruption == "missing":
            storage.remove(dataset.storage_key)
        elif corruption == "size":
            dataset.size_bytes = dataset.size_bytes + 1  # type: ignore[operator]
        elif corruption == "hash":
            dataset.content_sha256 = b"x" * 32
        elif corruption == "rows":
            dataset.row_count = dataset.row_count + 1  # type: ignore[operator]
        else:
            dataset.column_names = ["id", "email", "other"]

    with pytest.raises(AnalysisDataIntegrityError):
        analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 0


def test_analysis_persistence_is_atomic_when_result_insert_fails(
    identity_database: DatabaseResources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id, dataset_id, _datasets, analyses, _storage = _ready_dataset(
        identity_database, tmp_path / "storage", key="atomic"
    )

    def fail_after_first_result(
        repository: ValidationResultRepository, results: list[ValidationResult]
    ) -> None:
        repository._session.add(results[0])
        repository._session.flush()
        raise RuntimeError("synthetic persistence failure")

    monkeypatch.setattr(ValidationResultRepository, "add_all", fail_after_first_result)
    with pytest.raises(RuntimeError, match="synthetic persistence failure"):
        analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 0
        assert session.scalar(select(func.count()).select_from(ValidationResult)) == 0


def test_corrupt_rule_or_unexpected_engine_failure_never_persists_history(
    identity_database: DatabaseResources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id, dataset_id, _datasets, analyses, _storage = _ready_dataset(
        identity_database, tmp_path / "storage", key="internal-failure"
    )
    with identity_database.session_factory() as session, session.begin():
        rule = session.scalar(
            select(ValidationRule)
            .where(
                ValidationRule.dataset_id == dataset_id,
                ValidationRule.rule_type == "required",
            )
            .limit(1)
        )
        assert rule is not None
        rule.configuration = {"extra": True}
    with pytest.raises(AnalysisDataIntegrityError):
        analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    with identity_database.session_factory() as session, session.begin():
        rule = session.scalar(
            select(ValidationRule)
            .where(
                ValidationRule.dataset_id == dataset_id,
                ValidationRule.rule_type == "required",
            )
            .limit(1)
        )
        assert rule is not None
        rule.configuration = {}

    def fail_engine(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("synthetic engine failure")

    monkeypatch.setattr("datacheck.analysis.service.validate", fail_engine)
    with pytest.raises(RuntimeError, match="synthetic engine failure"):
        analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 0


def test_history_snapshots_survive_reupload_rule_delete_and_new_rule(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, datasets, analyses, _storage = _ready_dataset(
        identity_database, tmp_path / "storage", key="history"
    )
    first = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)
    first_rule_ids = {result.source_rule_id for result in first.rule_results}

    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset_id,
        original_filename="replacement.csv",
        source=BytesIO(b"email,age,id\nnew@example.test,50,9\n"),
    )
    deleted_rule_id = first.rule_results[0].source_rule_id
    datasets.delete_rule(
        owner_id=owner_id,
        dataset_id=dataset_id,
        rule_id=deleted_rule_id,
    )
    new_rule = datasets.create_rule(
        owner_id=owner_id,
        dataset_id=dataset_id,
        rule_type="regex",
        target_column="id",
        configuration={"pattern": "^[0-9]+$"},
    )
    second = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    frozen = analyses.get_analysis(
        owner_id=owner_id,
        dataset_id=dataset_id,
        analysis_id=first.analysis_id,
    )
    assert frozen == first
    assert frozen.source.original_filename == "people.csv"
    assert frozen.source.content_sha256 != second.source.content_sha256
    assert deleted_rule_id in {result.source_rule_id for result in frozen.rule_results}
    assert new_rule.rule_id not in first_rule_ids
    assert new_rule.rule_id not in {result.source_rule_id for result in frozen.rule_results}
    assert new_rule.rule_id in {result.source_rule_id for result in second.rule_results}

    listing = analyses.list_analyses(owner_id=owner_id, dataset_id=dataset_id, limit=1, offset=0)
    assert [item.analysis_id for item in listing] == [second.analysis_id]
    assert (
        analyses.list_analyses(owner_id=owner_id, dataset_id=dataset_id, limit=1, offset=1)[
            0
        ].analysis_id
        == first.analysis_id
    )


def test_analysis_snapshot_loads_all_rules_without_public_pagination(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "all-rules")
    datasets, analyses, _storage = _services(identity_database, tmp_path / "storage")
    dataset = datasets.create_dataset(owner_id=owner_id, name="All rules")
    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="values.csv",
        source=BytesIO(b"value\nvalue-1\n"),
    )
    with identity_database.session_factory() as session, session.begin():
        session.add_all(
            [
                ValidationRule(
                    id=uuid.uuid4(),
                    dataset_id=dataset.dataset_id,
                    rule_type="regex",
                    target_column="value",
                    configuration={"pattern": f"value-{index}|other"},
                    created_at=_NOW + timedelta(microseconds=index),
                )
                for index in range(101)
            ]
        )

    detail = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset.dataset_id)

    assert len(detail.rule_results) == 101
    assert [result.rule_position for result in detail.rule_results] == list(range(101))


def test_hash_snapshot_matches_exact_captured_file(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, _datasets, analyses, storage = _ready_dataset(
        identity_database, tmp_path / "storage", key="hash"
    )
    detail = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)
    file_content = next(storage.root.glob("*.csv")).read_bytes()
    assert detail.source.content_sha256 == hashlib.sha256(file_content).digest()


def test_history_does_not_recompute_from_mutated_database_rows(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, _datasets, analyses, _storage = _ready_dataset(
        identity_database, tmp_path / "storage", key="frozen"
    )
    detail = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)
    with identity_database.engine.begin() as connection:
        connection.execute(
            update(ValidationRule)
            .where(ValidationRule.dataset_id == dataset_id)
            .values(configuration={"pattern": "changed"})
        )

    assert (
        analyses.get_analysis(
            owner_id=owner_id,
            dataset_id=dataset_id,
            analysis_id=detail.analysis_id,
        )
        == detail
    )
