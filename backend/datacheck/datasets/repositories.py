import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from datacheck.datasets.models import Dataset, ValidationRule


class DatasetRepository:
    """Perform owner-scoped dataset persistence without committing transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, dataset: Dataset) -> None:
        self._session.add(dataset)

    def list_for_owner(self, owner_id: uuid.UUID, *, limit: int, offset: int) -> list[Dataset]:
        statement = (
            select(Dataset)
            .where(Dataset.owner_id == owner_id)
            .order_by(Dataset.created_at, Dataset.id)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def get_for_owner(self, *, dataset_id: uuid.UUID, owner_id: uuid.UUID) -> Dataset | None:
        statement = select(Dataset).where(
            Dataset.id == dataset_id,
            Dataset.owner_id == owner_id,
        )
        return self._session.scalar(statement)

    def get_for_owner_for_update(
        self, *, dataset_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Dataset | None:
        statement = (
            select(Dataset)
            .where(Dataset.id == dataset_id, Dataset.owner_id == owner_id)
            .with_for_update()
        )
        return self._session.scalar(statement)


class ValidationRuleRepository:
    """Persist rules only after their owner-scoped dataset boundary is established."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, rule: ValidationRule) -> None:
        self._session.add(rule)

    def target_columns(self, dataset_id: uuid.UUID) -> set[str]:
        statement = select(ValidationRule.target_column).where(
            ValidationRule.dataset_id == dataset_id
        )
        return set(self._session.scalars(statement))

    def list_for_dataset(
        self,
        *,
        dataset_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[ValidationRule]:
        statement = (
            select(ValidationRule)
            .where(ValidationRule.dataset_id == dataset_id)
            .order_by(ValidationRule.created_at, ValidationRule.id)
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def list_all_for_dataset(self, dataset_id: uuid.UUID) -> list[ValidationRule]:
        """Return the complete ordered rule set for an analysis snapshot."""
        statement = (
            select(ValidationRule)
            .where(ValidationRule.dataset_id == dataset_id)
            .order_by(ValidationRule.created_at, ValidationRule.id)
        )
        return list(self._session.scalars(statement))

    def get(self, *, dataset_id: uuid.UUID, rule_id: uuid.UUID) -> ValidationRule | None:
        statement = select(ValidationRule).where(
            ValidationRule.id == rule_id,
            ValidationRule.dataset_id == dataset_id,
        )
        return self._session.scalar(statement)

    def delete(self, rule: ValidationRule) -> None:
        self._session.delete(rule)
