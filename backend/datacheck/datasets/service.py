import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import BinaryIO

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from datacheck.datasets.csv import CsvStructureError, scan_csv
from datacheck.datasets.models import Dataset, ValidationRule
from datacheck.datasets.policies import (
    DatasetPolicyError,
    normalize_csv_filename,
    normalize_dataset_name,
    validate_target_column,
)
from datacheck.datasets.repositories import DatasetRepository, ValidationRuleRepository
from datacheck.datasets.storage import FileTooLarge, LocalDatasetStorage

logger = logging.getLogger(__name__)


class DatasetNotFound(Exception):
    pass


class DatasetNotReady(Exception):
    pass


class UnknownColumn(Exception):
    pass


class DuplicateRule(Exception):
    pass


class IncompatibleUpload(Exception):
    pass


@dataclass(frozen=True, slots=True)
class UploadReference:
    original_filename: str
    size_bytes: int
    row_count: int
    columns: tuple[str, ...]
    content_sha256: bytes
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetReference:
    dataset_id: uuid.UUID
    name: str
    created_at: datetime
    updated_at: datetime
    upload: UploadReference | None


@dataclass(frozen=True, slots=True)
class ValidationRuleReference:
    rule_id: uuid.UUID
    dataset_id: uuid.UUID
    rule_type: str
    target_column: str
    configuration: dict[str, object]
    created_at: datetime


class DatasetService:
    """Own dataset transactions and the PostgreSQL/filesystem consistency boundary."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        storage: LocalDatasetStorage,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_dataset(self, *, owner_id: uuid.UUID, name: str) -> DatasetReference:
        normalized_name = normalize_dataset_name(name)
        now = self._now()
        dataset = Dataset(
            id=uuid.uuid4(),
            owner_id=owner_id,
            name=normalized_name,
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as database_session, database_session.begin():
            DatasetRepository(database_session).add(dataset)
            database_session.flush()
        return self._dataset_reference(dataset)

    def list_datasets(
        self, *, owner_id: uuid.UUID, limit: int, offset: int
    ) -> list[DatasetReference]:
        with self._session_factory() as database_session, database_session.begin():
            rows = DatasetRepository(database_session).list_for_owner(
                owner_id, limit=limit, offset=offset
            )
            return [self._dataset_reference(row) for row in rows]

    def get_dataset(self, *, owner_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetReference:
        with self._session_factory() as database_session, database_session.begin():
            dataset = DatasetRepository(database_session).get_for_owner(
                dataset_id=dataset_id, owner_id=owner_id
            )
            if dataset is None:
                raise DatasetNotFound
            return self._dataset_reference(dataset)

    def upload_csv(
        self,
        *,
        owner_id: uuid.UUID,
        dataset_id: uuid.UUID,
        original_filename: str | None,
        source: BinaryIO,
    ) -> DatasetReference:
        safe_filename = normalize_csv_filename(original_filename)
        with self._session_factory() as database_session, database_session.begin():
            if (
                DatasetRepository(database_session).get_for_owner(
                    dataset_id=dataset_id, owner_id=owner_id
                )
                is None
            ):
                raise DatasetNotFound

        candidate = self._storage.write_candidate(source)
        installed_key: str | None = None
        try:
            structure = scan_csv(candidate.path)
            now = self._now()
            new_key = self._storage.new_storage_key()
            old_key: str | None = None

            with self._session_factory() as database_session, database_session.begin():
                datasets = DatasetRepository(database_session)
                rules = ValidationRuleRepository(database_session)
                dataset = datasets.get_for_owner_for_update(
                    dataset_id=dataset_id, owner_id=owner_id
                )
                if dataset is None:
                    raise DatasetNotFound
                if not rules.target_columns(dataset.id).issubset(structure.column_names):
                    raise IncompatibleUpload

                old_key = dataset.storage_key
                installed_key = new_key
                self._storage.install(candidate, new_key)
                dataset.original_filename = safe_filename
                dataset.storage_key = new_key
                dataset.content_sha256 = candidate.content_sha256
                dataset.size_bytes = candidate.size_bytes
                dataset.row_count = structure.row_count
                dataset.column_names = list(structure.column_names)
                dataset.uploaded_at = now
                dataset.updated_at = now
                database_session.flush()
                result = self._dataset_reference(dataset)

            if old_key is not None and old_key != new_key:
                try:
                    self._storage.remove(old_key)
                except OSError:
                    # The committed row points to a complete file. A failed cleanup may
                    # leave an orphan but must not invalidate the correct active upload.
                    logger.warning(
                        "Failed to remove superseded dataset file.",
                        extra={"dataset_id": str(dataset_id)},
                    )
            return result
        except BaseException:
            self._storage.discard_candidate(candidate)
            if installed_key is not None:
                try:
                    self._storage.remove(installed_key)
                except OSError:
                    pass
            raise

    def create_rule(
        self,
        *,
        owner_id: uuid.UUID,
        dataset_id: uuid.UUID,
        rule_type: str,
        target_column: str,
        configuration: dict[str, object],
    ) -> ValidationRuleReference:
        safe_column = validate_target_column(target_column)
        now = self._now()
        rule = ValidationRule(
            id=uuid.uuid4(),
            dataset_id=dataset_id,
            rule_type=rule_type,
            target_column=safe_column,
            configuration=configuration,
            created_at=now,
        )
        try:
            with self._session_factory() as database_session, database_session.begin():
                dataset = DatasetRepository(database_session).get_for_owner_for_update(
                    dataset_id=dataset_id, owner_id=owner_id
                )
                if dataset is None:
                    raise DatasetNotFound
                if dataset.column_names is None:
                    raise DatasetNotReady
                if safe_column not in dataset.column_names:
                    raise UnknownColumn
                ValidationRuleRepository(database_session).add(rule)
                database_session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_validation_rules_definition":
                raise DuplicateRule from None
            raise
        return self._rule_reference(rule)

    def list_rules(
        self,
        *,
        owner_id: uuid.UUID,
        dataset_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[ValidationRuleReference]:
        with self._session_factory() as database_session, database_session.begin():
            if (
                DatasetRepository(database_session).get_for_owner(
                    dataset_id=dataset_id, owner_id=owner_id
                )
                is None
            ):
                raise DatasetNotFound
            rows = ValidationRuleRepository(database_session).list_for_dataset(
                dataset_id=dataset_id, limit=limit, offset=offset
            )
            return [self._rule_reference(row) for row in rows]

    def delete_rule(
        self,
        *,
        owner_id: uuid.UUID,
        dataset_id: uuid.UUID,
        rule_id: uuid.UUID,
    ) -> None:
        with self._session_factory() as database_session, database_session.begin():
            if (
                DatasetRepository(database_session).get_for_owner(
                    dataset_id=dataset_id, owner_id=owner_id
                )
                is None
            ):
                raise DatasetNotFound
            repository = ValidationRuleRepository(database_session)
            rule = repository.get(dataset_id=dataset_id, rule_id=rule_id)
            if rule is None:
                raise DatasetNotFound
            repository.delete(rule)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("dataset clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _dataset_reference(dataset: Dataset) -> DatasetReference:
        upload: UploadReference | None = None
        if dataset.storage_key is not None:
            assert dataset.original_filename is not None
            assert dataset.content_sha256 is not None
            assert dataset.size_bytes is not None
            assert dataset.row_count is not None
            assert dataset.column_names is not None
            assert dataset.uploaded_at is not None
            upload = UploadReference(
                original_filename=dataset.original_filename,
                size_bytes=dataset.size_bytes,
                row_count=dataset.row_count,
                columns=tuple(dataset.column_names),
                content_sha256=dataset.content_sha256,
                uploaded_at=dataset.uploaded_at,
            )
        return DatasetReference(
            dataset_id=dataset.id,
            name=dataset.name,
            created_at=dataset.created_at,
            updated_at=dataset.updated_at,
            upload=upload,
        )

    @staticmethod
    def _rule_reference(rule: ValidationRule) -> ValidationRuleReference:
        return ValidationRuleReference(
            rule_id=rule.id,
            dataset_id=rule.dataset_id,
            rule_type=rule.rule_type,
            target_column=rule.target_column,
            configuration=dict(rule.configuration),
            created_at=rule.created_at,
        )

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        diagnostic = getattr(error.orig, "diag", None)
        name = getattr(diagnostic, "constraint_name", None)
        return name if isinstance(name, str) else None


__all__ = [
    "CsvStructureError",
    "DatasetNotFound",
    "DatasetNotReady",
    "DatasetPolicyError",
    "DatasetService",
    "DuplicateRule",
    "FileTooLarge",
    "IncompatibleUpload",
    "UnknownColumn",
]
