import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import delete, func, select

from datacheck.datasets.models import Dataset, ValidationRule
from datacheck.datasets.service import (
    DatasetService,
    DuplicateRule,
    IncompatibleUpload,
    UnknownColumn,
)
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.identity.models import User
from datacheck.infrastructure.database import DatabaseResources

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 6, 2, 12, tzinfo=UTC)


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


def _service(resources: DatabaseResources, root: Path) -> DatasetService:
    return DatasetService(
        session_factory=resources.session_factory,
        storage=LocalDatasetStorage(root),
        clock=lambda: _NOW,
    )


@pytest.fixture(autouse=True)
def clean_dataset_concurrency_rows(identity_database: DatabaseResources) -> None:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(User))


def test_concurrent_uploads_leave_one_complete_active_file(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "upload-race")
    root = tmp_path / "storage"
    service = _service(identity_database, root)
    dataset = service.create_dataset(owner_id=owner_id, name="Upload race")
    barrier = Barrier(2)
    contents = (b"id,value\n1,first\n", b"id,value\n2,second\n")

    def upload(index: int) -> bytes:
        actor = _service(identity_database, root)
        barrier.wait()
        result = actor.upload_csv(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            original_filename=f"upload-{index}.csv",
            source=BytesIO(contents[index]),
        )
        assert result.upload is not None
        return result.upload.content_sha256

    with ThreadPoolExecutor(max_workers=2) as executor:
        hashes = list(executor.map(upload, (0, 1)))

    active = service.get_dataset(owner_id=owner_id, dataset_id=dataset.dataset_id)
    assert active.upload is not None
    assert active.upload.content_sha256 in hashes
    files = list(root.glob("*.csv"))
    assert len(files) == 1
    assert files[0].read_bytes() in contents
    assert not list(root.glob(".candidate-*"))


def test_concurrent_identical_rules_have_exactly_one_winner(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "rule-race")
    root = tmp_path / "storage"
    service = _service(identity_database, root)
    dataset = service.create_dataset(owner_id=owner_id, name="Rule race")
    service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="rules.csv",
        source=BytesIO(b"id\n1\n"),
    )
    barrier = Barrier(2)

    def create_rule(_: int) -> str:
        actor = _service(identity_database, root)
        barrier.wait()
        try:
            actor.create_rule(
                owner_id=owner_id,
                dataset_id=dataset.dataset_id,
                rule_type="required",
                target_column="id",
                configuration={},
            )
        except DuplicateRule:
            return "duplicate"
        return "created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(create_rule, (0, 1)))

    assert sorted(outcomes) == ["created", "duplicate"]
    with identity_database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ValidationRule)) == 1


def test_upload_and_rule_creation_share_lock_and_never_leave_unknown_column_rule(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "column-race")
    root = tmp_path / "storage"
    service = _service(identity_database, root)
    dataset = service.create_dataset(owner_id=owner_id, name="Column race")
    service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="initial.csv",
        source=BytesIO(b"id,keep\n1,x\n"),
    )
    barrier = Barrier(2)

    def replace_upload() -> str:
        actor = _service(identity_database, root)
        barrier.wait()
        try:
            actor.upload_csv(
                owner_id=owner_id,
                dataset_id=dataset.dataset_id,
                original_filename="replacement.csv",
                source=BytesIO(b"id\n2\n"),
            )
        except IncompatibleUpload:
            return "upload_rejected"
        return "upload_replaced"

    def add_rule() -> str:
        actor = _service(identity_database, root)
        barrier.wait()
        try:
            actor.create_rule(
                owner_id=owner_id,
                dataset_id=dataset.dataset_id,
                rule_type="required",
                target_column="keep",
                configuration={},
            )
        except UnknownColumn:
            return "rule_rejected"
        return "rule_created"

    with ThreadPoolExecutor(max_workers=2) as executor:
        upload_future = executor.submit(replace_upload)
        rule_future = executor.submit(add_rule)
        outcomes = {upload_future.result(), rule_future.result()}

    assert outcomes in (
        {"upload_rejected", "rule_created"},
        {"upload_replaced", "rule_rejected"},
    )
    with identity_database.session_factory() as session:
        stored = session.get(Dataset, dataset.dataset_id)
        assert stored is not None and stored.column_names is not None
        targets = set(
            session.scalars(
                select(ValidationRule.target_column).where(
                    ValidationRule.dataset_id == dataset.dataset_id
                )
            )
        )
        assert targets.issubset(set(stored.column_names))
    assert len(list(root.glob("*.csv"))) == 1
    assert not list(root.glob(".candidate-*"))
