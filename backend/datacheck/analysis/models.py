import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from datacheck.infrastructure.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Analysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_analyses"),
        CheckConstraint(
            "octet_length(source_content_sha256) = 32",
            name="ck_analyses_source_content_sha256_length",
        ),
        CheckConstraint(
            "source_size_bytes BETWEEN 1 AND 10485760",
            name="ck_analyses_source_size_bytes",
        ),
        CheckConstraint("source_row_count >= 0", name="ck_analyses_source_row_count"),
        CheckConstraint(
            "jsonb_typeof(source_column_names) = 'array' "
            "AND jsonb_array_length(source_column_names) BETWEEN 1 AND 256",
            name="ck_analyses_source_column_names",
        ),
        CheckConstraint(
            "total_violation_count >= 0",
            name="ck_analyses_total_violation_count",
        ),
        CheckConstraint(
            "quality_score IS NULL OR quality_score BETWEEN 0.00 AND 100.00",
            name="ck_analyses_quality_score",
        ),
        Index("ix_analyses_dataset_created_id", "dataset_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("datasets.id", name="fk_analyses_dataset_id_datasets", ondelete="CASCADE"),
        nullable=False,
    )
    source_original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_content_sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_row_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_column_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_violation_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )


class ValidationResult(Base):
    __tablename__ = "validation_results"
    __table_args__ = (
        PrimaryKeyConstraint("analysis_id", "rule_position", name="pk_validation_results"),
        UniqueConstraint(
            "analysis_id",
            "source_rule_id",
            name="uq_validation_results_analysis_source_rule",
        ),
        CheckConstraint("rule_position >= 0", name="ck_validation_results_rule_position"),
        CheckConstraint(
            "rule_type IN ('required', 'unique', 'type', 'range', 'regex')",
            name="ck_validation_results_rule_type",
        ),
        CheckConstraint(
            "char_length(target_column) BETWEEN 1 AND 128 AND target_column = btrim(target_column)",
            name="ck_validation_results_target_column",
        ),
        CheckConstraint(
            "jsonb_typeof(configuration) = 'object'",
            name="ck_validation_results_configuration_object",
        ),
        CheckConstraint(
            "evaluated_count >= 0 AND passed_count >= 0 "
            "AND violation_count >= 0 AND skipped_count >= 0",
            name="ck_validation_results_nonnegative_counts",
        ),
        CheckConstraint(
            "evaluated_count = passed_count + violation_count",
            name="ck_validation_results_count_balance",
        ),
        CheckConstraint(
            "jsonb_typeof(violation_samples) = 'array' "
            "AND jsonb_array_length(violation_samples) <= 20",
            name="ck_validation_results_violation_samples",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "analyses.id",
            name="fk_validation_results_analysis_id_analyses",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    rule_position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_rule_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_column: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    evaluated_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    passed_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    violation_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    skipped_count: Mapped[int] = mapped_column(BigInteger, nullable=False)
    violation_samples: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
