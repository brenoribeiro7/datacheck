import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
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


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_datasets"),
        UniqueConstraint("storage_key", name="uq_datasets_storage_key"),
        CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100 AND name = btrim(name)",
            name="ck_datasets_name",
        ),
        CheckConstraint(
            "original_filename IS NULL OR char_length(original_filename) BETWEEN 1 AND 255",
            name="ck_datasets_original_filename",
        ),
        CheckConstraint(
            "storage_key IS NULL OR storage_key ~ '^[0-9a-f]{32}[.]csv$'",
            name="ck_datasets_storage_key_format",
        ),
        CheckConstraint(
            "content_sha256 IS NULL OR octet_length(content_sha256) = 32",
            name="ck_datasets_content_sha256_length",
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760",
            name="ck_datasets_size_bytes",
        ),
        CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_datasets_row_count",
        ),
        CheckConstraint(
            "column_names IS NULL OR (jsonb_typeof(column_names) = 'array' "
            "AND jsonb_array_length(column_names) BETWEEN 1 AND 256)",
            name="ck_datasets_column_names",
        ),
        CheckConstraint(
            "((original_filename IS NULL AND storage_key IS NULL AND content_sha256 IS NULL "
            "AND size_bytes IS NULL AND row_count IS NULL AND column_names IS NULL "
            "AND uploaded_at IS NULL) OR (original_filename IS NOT NULL "
            "AND storage_key IS NOT NULL AND content_sha256 IS NOT NULL "
            "AND size_bytes IS NOT NULL AND row_count IS NOT NULL "
            "AND column_names IS NOT NULL AND uploaded_at IS NOT NULL))",
            name="ck_datasets_upload_metadata_all_or_none",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_datasets_updated_not_before_created",
        ),
        CheckConstraint(
            "uploaded_at IS NULL OR (uploaded_at >= created_at AND updated_at >= uploaded_at)",
            name="ck_datasets_upload_timestamps",
        ),
        Index("ix_datasets_owner_created_id", "owner_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_datasets_owner_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content_sha256: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_names: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )


class ValidationRule(Base):
    __tablename__ = "validation_rules"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_validation_rules"),
        UniqueConstraint(
            "dataset_id",
            "rule_type",
            "target_column",
            "configuration",
            name="uq_validation_rules_definition",
        ),
        CheckConstraint(
            "rule_type IN ('required', 'unique', 'type', 'range', 'regex')",
            name="ck_validation_rules_type",
        ),
        CheckConstraint(
            "char_length(target_column) BETWEEN 1 AND 128 AND target_column = btrim(target_column)",
            name="ck_validation_rules_target_column",
        ),
        CheckConstraint(
            "jsonb_typeof(configuration) = 'object'",
            name="ck_validation_rules_configuration_object",
        ),
        Index(
            "ix_validation_rules_dataset_created_id",
            "dataset_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, nullable=False)
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "datasets.id",
            name="fk_validation_rules_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_column: Mapped[str] = mapped_column(String(128), nullable=False)
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
