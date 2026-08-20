import hashlib
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from datacheck.analysis.adapters import (
    AdaptedRule,
    AnalysisDataIntegrityError,
    PersistedRuleSnapshot,
    adapt_rules,
    load_textual_csv,
)
from datacheck.analysis.models import Analysis, ValidationResult
from datacheck.analysis.repositories import AnalysisRepository, ValidationResultRepository
from datacheck.analysis.score import calculate_quality_score
from datacheck.datasets.csv import MAX_CSV_BYTES
from datacheck.datasets.repositories import DatasetRepository, ValidationRuleRepository
from datacheck.datasets.service import DatasetNotFound, DatasetNotReady
from datacheck.datasets.storage import LocalDatasetStorage
from datacheck.validation import ValidationEngineResult, ValidationInputError, validate

logger = logging.getLogger(__name__)
_READ_CHUNK_BYTES = 65_536


class AnalysisRequiresRules(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    original_filename: str
    content_sha256: bytes
    size_bytes: int
    row_count: int
    column_names: tuple[str, ...]
    uploaded_at: datetime


@dataclass(frozen=True, slots=True)
class ViolationSampleReference:
    row_number: int
    value_preview: str | None
    truncated: bool


@dataclass(frozen=True, slots=True)
class ValidationResultReference:
    rule_position: int
    source_rule_id: uuid.UUID
    rule_type: str
    target_column: str
    configuration: dict[str, object]
    evaluated_count: int
    passed_count: int
    violation_count: int
    skipped_count: int
    violation_samples: tuple[ViolationSampleReference, ...]


@dataclass(frozen=True, slots=True)
class AnalysisSummaryReference:
    analysis_id: uuid.UUID
    dataset_id: uuid.UUID
    quality_score: Decimal | None
    source_row_count: int
    total_violation_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnalysisDetailReference(AnalysisSummaryReference):
    source: SourceSnapshot
    rule_results: tuple[ValidationResultReference, ...]


class AnalysisService:
    """Coordinate a bounded source snapshot, pure validation, and atomic history."""

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

    def create_analysis(
        self, *, owner_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> AnalysisDetailReference:
        try:
            source, rules, content = self._capture_snapshot(
                owner_id=owner_id, dataset_id=dataset_id
            )
            frame = load_textual_csv(
                content,
                expected_columns=source.column_names,
                expected_row_count=source.row_count,
            )
            adapted_rules = adapt_rules(rules)
            try:
                engine_result = validate(frame, [rule.spec for rule in adapted_rules])
            except ValidationInputError:
                raise AnalysisDataIntegrityError(
                    "validation engine rejected persisted state"
                ) from None
            return self._persist_analysis(
                dataset_id=dataset_id,
                source=source,
                adapted_rules=adapted_rules,
                engine_result=engine_result,
            )
        except AnalysisDataIntegrityError:
            logger.error(
                "Dataset analysis failed an integrity check.",
                extra={"dataset_id": str(dataset_id), "event_code": "analysis_integrity_failure"},
            )
            raise

    def list_analyses(
        self,
        *,
        owner_id: uuid.UUID,
        dataset_id: uuid.UUID,
        limit: int,
        offset: int,
    ) -> list[AnalysisSummaryReference]:
        with self._session_factory() as database_session, database_session.begin():
            if (
                DatasetRepository(database_session).get_for_owner(
                    dataset_id=dataset_id, owner_id=owner_id
                )
                is None
            ):
                raise DatasetNotFound
            rows = AnalysisRepository(database_session).list_for_dataset_owner(
                dataset_id=dataset_id,
                owner_id=owner_id,
                limit=limit,
                offset=offset,
            )
            return [self._summary_reference(row) for row in rows]

    def get_analysis(
        self,
        *,
        owner_id: uuid.UUID,
        dataset_id: uuid.UUID,
        analysis_id: uuid.UUID,
    ) -> AnalysisDetailReference:
        with self._session_factory() as database_session, database_session.begin():
            analysis = AnalysisRepository(database_session).get_for_dataset_owner(
                analysis_id=analysis_id,
                dataset_id=dataset_id,
                owner_id=owner_id,
            )
            if analysis is None:
                raise DatasetNotFound
            results = ValidationResultRepository(database_session).list_for_analysis(analysis.id)
            return self._detail_reference(analysis, results)

    def _capture_snapshot(
        self, *, owner_id: uuid.UUID, dataset_id: uuid.UUID
    ) -> tuple[SourceSnapshot, tuple[PersistedRuleSnapshot, ...], bytes]:
        with self._session_factory() as database_session, database_session.begin():
            dataset = DatasetRepository(database_session).get_for_owner_for_update(
                dataset_id=dataset_id, owner_id=owner_id
            )
            if dataset is None:
                raise DatasetNotFound
            if (
                dataset.storage_key is None
                or dataset.original_filename is None
                or dataset.content_sha256 is None
                or dataset.size_bytes is None
                or dataset.row_count is None
                or dataset.column_names is None
                or dataset.uploaded_at is None
            ):
                raise DatasetNotReady

            source = SourceSnapshot(
                original_filename=dataset.original_filename,
                content_sha256=bytes(dataset.content_sha256),
                size_bytes=dataset.size_bytes,
                row_count=dataset.row_count,
                column_names=tuple(dataset.column_names),
                uploaded_at=dataset.uploaded_at,
            )
            rows = ValidationRuleRepository(database_session).list_all_for_dataset(dataset.id)
            if not rows:
                raise AnalysisRequiresRules
            rules = tuple(
                PersistedRuleSnapshot(
                    rule_id=row.id,
                    rule_type=row.rule_type,
                    target_column=row.target_column,
                    configuration=dict(row.configuration),
                )
                for row in rows
            )
            content = self._read_verified_content(dataset.storage_key, source)
            return source, rules, content

    def _read_verified_content(self, storage_key: str, source: SourceSnapshot) -> bytes:
        digest = hashlib.sha256()
        content = bytearray()
        try:
            with self._storage.open_binary(storage_key) as source_file:
                while chunk := source_file.read(_READ_CHUNK_BYTES):
                    content.extend(chunk)
                    if len(content) > MAX_CSV_BYTES:
                        raise AnalysisDataIntegrityError("active CSV exceeds the byte limit")
                    digest.update(chunk)
        except (OSError, ValueError):
            raise AnalysisDataIntegrityError("active CSV is unavailable") from None
        if len(content) != source.size_bytes:
            raise AnalysisDataIntegrityError("active CSV size does not match persisted metadata")
        if digest.digest() != source.content_sha256:
            raise AnalysisDataIntegrityError("active CSV hash does not match persisted metadata")
        return bytes(content)

    def _persist_analysis(
        self,
        *,
        dataset_id: uuid.UUID,
        source: SourceSnapshot,
        adapted_rules: tuple[AdaptedRule, ...],
        engine_result: ValidationEngineResult,
    ) -> AnalysisDetailReference:
        if len(adapted_rules) != len(engine_result.rule_results):
            raise AnalysisDataIntegrityError("validation engine result count is inconsistent")
        if engine_result.total_rows != source.row_count:
            raise AnalysisDataIntegrityError("validation engine row count is inconsistent")

        analysis_id = uuid.uuid4()
        created_at = self._now()
        score = calculate_quality_score(engine_result.rule_results)
        total_violations = sum(result.violation_count for result in engine_result.rule_results)
        analysis = Analysis(
            id=analysis_id,
            dataset_id=dataset_id,
            source_original_filename=source.original_filename,
            source_content_sha256=source.content_sha256,
            source_size_bytes=source.size_bytes,
            source_row_count=source.row_count,
            source_column_names=list(source.column_names),
            source_uploaded_at=source.uploaded_at,
            total_violation_count=total_violations,
            quality_score=score,
            created_at=created_at,
        )
        results = self._result_models(analysis_id, source, adapted_rules, engine_result)
        with self._session_factory() as database_session, database_session.begin():
            AnalysisRepository(database_session).add(analysis)
            ValidationResultRepository(database_session).add_all(results)
            database_session.flush()
        return self._detail_reference(analysis, results)

    @staticmethod
    def _result_models(
        analysis_id: uuid.UUID,
        source: SourceSnapshot,
        adapted_rules: tuple[AdaptedRule, ...],
        engine_result: ValidationEngineResult,
    ) -> list[ValidationResult]:
        rows: list[ValidationResult] = []
        for position, (adapted, result) in enumerate(
            zip(adapted_rules, engine_result.rule_results, strict=True)
        ):
            if result.rule != adapted.spec:
                raise AnalysisDataIntegrityError("validation engine result order is inconsistent")
            if result.evaluated_count + result.skipped_count != source.row_count:
                raise AnalysisDataIntegrityError("validation engine counts are inconsistent")
            samples = [
                {
                    "row_number": sample.row_number,
                    "value_preview": sample.value_preview,
                    "truncated": sample.truncated,
                }
                for sample in result.violation_samples
            ]
            rows.append(
                ValidationResult(
                    analysis_id=analysis_id,
                    rule_position=position,
                    source_rule_id=adapted.rule_id,
                    rule_type=adapted.rule_type,
                    target_column=adapted.target_column,
                    configuration=dict(adapted.configuration),
                    evaluated_count=result.evaluated_count,
                    passed_count=result.passed_count,
                    violation_count=result.violation_count,
                    skipped_count=result.skipped_count,
                    violation_samples=samples,
                )
            )
        return rows

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("analysis clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _summary_reference(analysis: Analysis) -> AnalysisSummaryReference:
        return AnalysisSummaryReference(
            analysis_id=analysis.id,
            dataset_id=analysis.dataset_id,
            quality_score=analysis.quality_score,
            source_row_count=analysis.source_row_count,
            total_violation_count=analysis.total_violation_count,
            created_at=analysis.created_at,
        )

    @classmethod
    def _detail_reference(
        cls, analysis: Analysis, results: list[ValidationResult]
    ) -> AnalysisDetailReference:
        summary = cls._summary_reference(analysis)
        return AnalysisDetailReference(
            analysis_id=summary.analysis_id,
            dataset_id=summary.dataset_id,
            quality_score=summary.quality_score,
            source_row_count=summary.source_row_count,
            total_violation_count=summary.total_violation_count,
            created_at=summary.created_at,
            source=SourceSnapshot(
                original_filename=analysis.source_original_filename,
                content_sha256=analysis.source_content_sha256,
                size_bytes=analysis.source_size_bytes,
                row_count=analysis.source_row_count,
                column_names=tuple(analysis.source_column_names),
                uploaded_at=analysis.source_uploaded_at,
            ),
            rule_results=tuple(cls._result_reference(result) for result in results),
        )

    @staticmethod
    def _result_reference(result: ValidationResult) -> ValidationResultReference:
        return ValidationResultReference(
            rule_position=result.rule_position,
            source_rule_id=result.source_rule_id,
            rule_type=result.rule_type,
            target_column=result.target_column,
            configuration=dict(result.configuration),
            evaluated_count=result.evaluated_count,
            passed_count=result.passed_count,
            violation_count=result.violation_count,
            skipped_count=result.skipped_count,
            violation_samples=tuple(
                AnalysisService._sample_reference(sample) for sample in result.violation_samples
            ),
        )

    @staticmethod
    def _sample_reference(sample: dict[str, object]) -> ViolationSampleReference:
        row_number = sample.get("row_number")
        value_preview = sample.get("value_preview")
        truncated = sample.get("truncated")
        if (
            isinstance(row_number, bool)
            or not isinstance(row_number, int)
            or row_number < 1
            or (value_preview is not None and not isinstance(value_preview, str))
            or not isinstance(truncated, bool)
        ):
            raise AnalysisDataIntegrityError("persisted violation sample is invalid")
        return ViolationSampleReference(
            row_number=row_number,
            value_preview=value_preview,
            truncated=truncated,
        )


__all__ = [
    "AnalysisDataIntegrityError",
    "AnalysisDetailReference",
    "AnalysisRequiresRules",
    "AnalysisService",
    "AnalysisSummaryReference",
]
