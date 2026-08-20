import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from datacheck.datasets.models import Dataset, ValidationRule
from datacheck.datasets.service import (
    DatasetNotFound,
    DatasetNotReady,
    DatasetService,
    DuplicateRule,
    IncompatibleUpload,
    UnknownColumn,
)
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.identity.models import User
from datacheck.infrastructure.database import DatabaseResources

pytestmark = pytest.mark.integration
_NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


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


def _service(
    resources: DatabaseResources,
    root: Path,
    *,
    now: datetime = _NOW,
) -> DatasetService:
    return DatasetService(
        session_factory=resources.session_factory,
        storage=LocalDatasetStorage(root),
        clock=lambda: now,
    )


@pytest.fixture(autouse=True)
def clean_dataset_service_rows(identity_database: DatabaseResources) -> None:
    with identity_database.engine.begin() as connection:
        connection.execute(delete(User))


def test_dataset_service_create_list_get_and_owner_isolation(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "owner")
    other_id = _insert_user(identity_database, "other")
    service = _service(identity_database, tmp_path / "storage")

    first = service.create_dataset(owner_id=owner_id, name=" First dataset ")
    second = service.create_dataset(owner_id=owner_id, name="Second dataset")
    service.create_dataset(owner_id=other_id, name="Other dataset")

    assert first.name == "First dataset"
    assert first.upload is None
    expected_ids = sorted((first.dataset_id, second.dataset_id))
    assert [
        row.dataset_id for row in service.list_datasets(owner_id=owner_id, limit=50, offset=0)
    ] == expected_ids
    assert (
        service.list_datasets(owner_id=owner_id, limit=1, offset=1)[0].dataset_id == expected_ids[1]
    )
    assert service.get_dataset(owner_id=owner_id, dataset_id=first.dataset_id) == first
    with pytest.raises(DatasetNotFound):
        service.get_dataset(owner_id=other_id, dataset_id=first.dataset_id)


def test_upload_persists_structural_metadata_and_compatible_reupload(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "upload")
    storage = LocalDatasetStorage(tmp_path / "storage")
    service = DatasetService(
        session_factory=identity_database.session_factory,
        storage=storage,
        clock=lambda: _NOW,
    )
    dataset = service.create_dataset(owner_id=owner_id, name="People")
    original = b"id,email\n1,first@example.test\n"

    uploaded = service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="people.CSV",
        source=BytesIO(original),
    )

    assert uploaded.upload is not None
    assert uploaded.upload.original_filename == "people.CSV"
    assert uploaded.upload.size_bytes == len(original)
    assert uploaded.upload.row_count == 1
    assert uploaded.upload.columns == ("id", "email")
    assert uploaded.upload.content_sha256 == hashlib.sha256(original).digest()
    files = list(storage.root.glob("*.csv"))
    assert len(files) == 1 and files[0].read_bytes() == original

    service.create_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_type="required",
        target_column="email",
        configuration={},
    )
    replacement = b"email,id,name\nsecond@example.test,2,Alice\n"
    replaced = service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="replacement.csv",
        source=BytesIO(replacement),
    )
    assert replaced.upload is not None
    assert replaced.upload.columns == ("email", "id", "name")
    files = list(storage.root.glob("*.csv"))
    assert len(files) == 1 and files[0].read_bytes() == replacement


def test_rule_lifecycle_requires_a_known_uploaded_column_and_rejects_duplicates(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "rules")
    other_id = _insert_user(identity_database, "rules-other")
    service = _service(identity_database, tmp_path / "storage")
    dataset = service.create_dataset(owner_id=owner_id, name="Rules")

    with pytest.raises(DatasetNotReady):
        service.create_rule(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            rule_type="required",
            target_column="id",
            configuration={},
        )

    service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="rules.csv",
        source=BytesIO(b"id,value\n1,x\n"),
    )
    with pytest.raises(UnknownColumn):
        service.create_rule(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            rule_type="required",
            target_column="missing",
            configuration={},
        )
    created = service.create_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_type="type",
        target_column="id",
        configuration={"expected_type": "integer"},
    )
    with pytest.raises(DuplicateRule):
        service.create_rule(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            rule_type="type",
            target_column="id",
            configuration={"expected_type": "integer"},
        )
    assert service.list_rules(
        owner_id=owner_id, dataset_id=dataset.dataset_id, limit=50, offset=0
    ) == [created]
    with pytest.raises(DatasetNotFound):
        service.list_rules(owner_id=other_id, dataset_id=dataset.dataset_id, limit=50, offset=0)
    service.delete_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_id=created.rule_id,
    )
    assert (
        service.list_rules(owner_id=owner_id, dataset_id=dataset.dataset_id, limit=50, offset=0)
        == []
    )


def test_incompatible_reupload_preserves_database_and_active_file(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "incompatible")
    storage = LocalDatasetStorage(tmp_path / "storage")
    service = DatasetService(
        session_factory=identity_database.session_factory,
        storage=storage,
        clock=lambda: _NOW,
    )
    dataset = service.create_dataset(owner_id=owner_id, name="Compatible")
    original = b"id,email\n1,a@example.test\n"
    before = service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="original.csv",
        source=BytesIO(original),
    )
    service.create_rule(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        rule_type="required",
        target_column="email",
        configuration={},
    )

    with pytest.raises(IncompatibleUpload):
        service.upload_csv(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            original_filename="bad.csv",
            source=BytesIO(b"id\n2\n"),
        )

    after = service.get_dataset(owner_id=owner_id, dataset_id=dataset.dataset_id)
    assert after == before
    files = list(storage.root.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == original


def test_database_failure_after_install_compensates_new_file_and_preserves_old_upload(
    identity_database: DatabaseResources,
    tmp_path: Path,
) -> None:
    owner_id = _insert_user(identity_database, "rollback")
    storage = LocalDatasetStorage(tmp_path / "storage")
    service = DatasetService(
        session_factory=identity_database.session_factory,
        storage=storage,
        clock=lambda: _NOW,
    )
    dataset = service.create_dataset(owner_id=owner_id, name="Rollback")
    original = b"id\n1\n"
    before = service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="original.csv",
        source=BytesIO(original),
    )

    invalid_clock_service = DatasetService(
        session_factory=identity_database.session_factory,
        storage=storage,
        clock=lambda: _NOW - timedelta(seconds=1),
    )
    with pytest.raises(IntegrityError):
        invalid_clock_service.upload_csv(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            original_filename="replacement.csv",
            source=BytesIO(b"id\n2\n"),
        )

    assert service.get_dataset(owner_id=owner_id, dataset_id=dataset.dataset_id) == before
    files = list(storage.root.iterdir())
    assert len(files) == 1 and files[0].read_bytes() == original
    with identity_database.session_factory() as session:
        assert session.scalars(select(Dataset)).one().storage_key == files[0].name
        assert session.scalar(select(ValidationRule)) is None


def test_failed_old_file_cleanup_does_not_undo_committed_reupload(
    identity_database: DatabaseResources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = _insert_user(identity_database, "cleanup")
    storage = LocalDatasetStorage(tmp_path / "storage")
    service = DatasetService(
        session_factory=identity_database.session_factory,
        storage=storage,
        clock=lambda: _NOW,
    )
    dataset = service.create_dataset(owner_id=owner_id, name="Cleanup")
    service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="old.csv",
        source=BytesIO(b"id\n1\n"),
    )
    old_key = next(storage.root.glob("*.csv")).name
    original_remove = storage.remove

    def fail_only_old_file(storage_key: str) -> None:
        if storage_key == old_key:
            raise OSError("synthetic cleanup failure")
        original_remove(storage_key)

    warnings: list[tuple[str, dict[str, object]]] = []

    def capture_warning(message: str, *, extra: dict[str, object]) -> None:
        warnings.append((message, extra))

    monkeypatch.setattr(storage, "remove", fail_only_old_file)
    monkeypatch.setattr("datacheck.datasets.service.logger.warning", capture_warning)
    replacement = service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="new.csv",
        source=BytesIO(b"id\n2\n"),
    )

    assert replacement.upload is not None
    assert replacement.upload.original_filename == "new.csv"
    assert len(list(storage.root.glob("*.csv"))) == 2
    assert warnings == [
        (
            "Failed to remove superseded dataset file.",
            {"dataset_id": str(dataset.dataset_id)},
        )
    ]
    assert "old.csv" not in repr(warnings)
    assert old_key not in repr(warnings)


def test_unexpected_post_commit_cleanup_failure_preserves_new_active_file(
    identity_database: DatabaseResources,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = _insert_user(identity_database, "unexpected-cleanup")
    storage = LocalDatasetStorage(tmp_path / "storage")
    service = DatasetService(
        session_factory=identity_database.session_factory,
        storage=storage,
        clock=lambda: _NOW,
    )
    dataset = service.create_dataset(owner_id=owner_id, name="Unexpected cleanup")
    original = b"id\n1\n"
    service.upload_csv(
        owner_id=owner_id,
        dataset_id=dataset.dataset_id,
        original_filename="old.csv",
        source=BytesIO(original),
    )
    old_key = next(storage.root.glob("*.csv")).name
    original_remove = storage.remove
    remove_calls: list[str] = []

    def fail_unexpectedly_for_old_file(storage_key: str) -> None:
        remove_calls.append(storage_key)
        if storage_key == old_key:
            raise RuntimeError("synthetic unexpected cleanup failure")
        original_remove(storage_key)

    monkeypatch.setattr(storage, "remove", fail_unexpectedly_for_old_file)
    replacement = b"id\n2\n"
    with pytest.raises(RuntimeError, match="synthetic unexpected cleanup failure"):
        service.upload_csv(
            owner_id=owner_id,
            dataset_id=dataset.dataset_id,
            original_filename="new.csv",
            source=BytesIO(replacement),
        )

    with identity_database.session_factory() as session:
        stored = session.get(Dataset, dataset.dataset_id)
        assert stored is not None
        assert stored.storage_key is not None
        new_key = stored.storage_key
        assert stored.original_filename == "new.csv"
        assert stored.content_sha256 == hashlib.sha256(replacement).digest()
        assert stored.size_bytes == len(replacement)
        assert stored.row_count == 1
        assert stored.column_names == ["id"]

    assert new_key != old_key
    assert remove_calls == [old_key]
    assert (storage.root / new_key).read_bytes() == replacement
    assert (storage.root / old_key).read_bytes() == original
