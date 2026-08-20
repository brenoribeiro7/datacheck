import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import delete, func, select

from datacheck.analysis.models import Analysis, ValidationResult
from datacheck.analysis.service import AnalysisDetailReference, AnalysisService
from datacheck.datasets.service import DatasetReference, DatasetService, ValidationRuleReference
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.identity.models import User
from datacheck.infrastructure.database import DatabaseResources

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 8, 4, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean_analysis_concurrency_rows(identity_database: DatabaseResources) -> None:
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


def _services(resources: DatabaseResources, root: Path) -> tuple[DatasetService, AnalysisService]:
    storage = LocalDatasetStorage(root)
    return (
        DatasetService(session_factory=resources.session_factory, storage=storage),
        AnalysisService(session_factory=resources.session_factory, storage=storage),
    )


def _ready(
    resources: DatabaseResources, root: Path, key: str
) -> tuple[uuid.UUID, uuid.UUID, DatasetService, AnalysisService, uuid.UUID]:
    owner_id = _insert_user(resources, key)
    datasets, analyses = _services(resources, root)
    dataset = datasets.create_dataset(owner_id=owner_id, name="Concurrent analysis")
    datasets.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="old.csv",
        source=BytesIO(b"id,value\n1,old\n"),
    )
    rule = datasets.create_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_type="required",
        target_column="value",
        configuration={},
    )
    return owner_id, dataset.dataset_id, datasets, analyses, rule.rule_id


def test_analysis_and_reupload_never_mix_source_metadata_and_bytes(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, datasets, analyses, _rule_id = _ready(
        identity_database, tmp_path / "storage", "analysis-upload"
    )
    barrier = Barrier(2)
    replacement = b"value,id\nnew,2\n"

    def analyze() -> AnalysisDetailReference:
        barrier.wait()
        return analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    def reupload() -> DatasetReference:
        barrier.wait()
        return datasets.upload_csv(
            owner_id=owner_id,
            dataset_id=dataset_id,
            original_filename="new.csv",
            source=BytesIO(replacement),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        analysis_future = executor.submit(analyze)
        upload_future = executor.submit(reupload)
        detail = analysis_future.result()
        upload_future.result()

    source = detail.source
    alternatives = {
        ("old.csv", hashlib.sha256(b"id,value\n1,old\n").digest(), ("id", "value")),
        ("new.csv", hashlib.sha256(replacement).digest(), ("value", "id")),
    }
    assert (source.original_filename, source.content_sha256, source.column_names) in alternatives


def test_analysis_and_create_rule_serialize_to_a_complete_rule_set(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, datasets, analyses, first_rule_id = _ready(
        identity_database, tmp_path / "storage", "analysis-rule"
    )
    barrier = Barrier(2)

    def analyze() -> AnalysisDetailReference:
        barrier.wait()
        return analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    def create_rule() -> ValidationRuleReference:
        barrier.wait()
        return datasets.create_rule(
            owner_id=owner_id,
            dataset_id=dataset_id,
            rule_type="unique",
            target_column="id",
            configuration={},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        analysis_future = executor.submit(analyze)
        rule_future = executor.submit(create_rule)
        detail = analysis_future.result()
        second_rule = rule_future.result()

    result_ids = {result.source_rule_id for result in detail.rule_results}
    assert result_ids in ({first_rule_id}, {first_rule_id, second_rule.rule_id})


def test_rule_deletion_after_capture_does_not_remove_historical_snapshot(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, datasets, analyses, rule_id = _ready(
        identity_database, tmp_path / "storage", "analysis-delete"
    )
    detail = analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    datasets.delete_rule(owner_id=owner_id, dataset_id=dataset_id, rule_id=rule_id)

    frozen = analyses.get_analysis(
        owner_id=owner_id,
        dataset_id=dataset_id,
        analysis_id=detail.analysis_id,
    )
    assert [result.source_rule_id for result in frozen.rule_results] == [rule_id]


def test_concurrent_analyses_persist_two_complete_independent_histories(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id, dataset_id, _datasets, analyses, _rule_id = _ready(
        identity_database, tmp_path / "storage", "analysis-analysis"
    )
    barrier = Barrier(2)

    def analyze(_: int) -> AnalysisDetailReference:
        barrier.wait()
        return analyses.create_analysis(owner_id=owner_id, dataset_id=dataset_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(analyze, (0, 1)))

    ids = {result.analysis_id for result in results}
    assert len(ids) == 2
    assert all(len(result.rule_results) == 1 for result in results)
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Analysis)) == 2
        assert session.scalar(select(func.count()).select_from(ValidationResult)) == 2
