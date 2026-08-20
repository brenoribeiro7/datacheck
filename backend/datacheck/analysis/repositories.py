import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from datacheck.analysis.models import Analysis, ValidationResult
from datacheck.datasets.models import Dataset


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, analysis: Analysis) -> None:
        self._session.add(analysis)

    def list_for_dataset_owner(
        self,
        *,
        dataset_id: uuid.UUID,
        owner_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[Analysis]:
        statement = (
            select(Analysis)
            .join(Dataset, Dataset.id == Analysis.dataset_id)
            .where(Analysis.dataset_id == dataset_id, Dataset.owner_id == owner_id)
            .order_by(Analysis.created_at.desc(), Analysis.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self._session.scalars(statement))

    def get_for_dataset_owner(
        self,
        *,
        analysis_id: uuid.UUID,
        dataset_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> Analysis | None:
        statement = (
            select(Analysis)
            .join(Dataset, Dataset.id == Analysis.dataset_id)
            .where(
                Analysis.id == analysis_id,
                Analysis.dataset_id == dataset_id,
                Dataset.owner_id == owner_id,
            )
        )
        return self._session.scalar(statement)


class ValidationResultRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_all(self, results: list[ValidationResult]) -> None:
        self._session.add_all(results)

    def list_for_analysis(self, analysis_id: uuid.UUID) -> list[ValidationResult]:
        statement = (
            select(ValidationResult)
            .where(ValidationResult.analysis_id == analysis_id)
            .order_by(ValidationResult.rule_position)
        )
        return list(self._session.scalars(statement))
