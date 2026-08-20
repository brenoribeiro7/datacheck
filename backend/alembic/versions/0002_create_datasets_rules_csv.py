"""Create datasets, validation rules, and CSV metadata.

Revision ID: 0002_datasets_rules_csv
Revises: 0001_identity_sessions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_datasets_rules_csv"
down_revision: str | None = "0001_identity_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=36), nullable=True),
        sa.Column("content_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("row_count", sa.BigInteger(), nullable=True),
        sa.Column("column_names", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 100 AND name = btrim(name)",
            name="ck_datasets_name",
        ),
        sa.CheckConstraint(
            "original_filename IS NULL OR char_length(original_filename) BETWEEN 1 AND 255",
            name="ck_datasets_original_filename",
        ),
        sa.CheckConstraint(
            "storage_key IS NULL OR storage_key ~ '^[0-9a-f]{32}[.]csv$'",
            name="ck_datasets_storage_key_format",
        ),
        sa.CheckConstraint(
            "content_sha256 IS NULL OR octet_length(content_sha256) = 32",
            name="ck_datasets_content_sha256_length",
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes BETWEEN 1 AND 10485760",
            name="ck_datasets_size_bytes",
        ),
        sa.CheckConstraint(
            "row_count IS NULL OR row_count >= 0",
            name="ck_datasets_row_count",
        ),
        sa.CheckConstraint(
            "column_names IS NULL OR (jsonb_typeof(column_names) = 'array' "
            "AND jsonb_array_length(column_names) BETWEEN 1 AND 256)",
            name="ck_datasets_column_names",
        ),
        sa.CheckConstraint(
            "((original_filename IS NULL AND storage_key IS NULL AND content_sha256 IS NULL "
            "AND size_bytes IS NULL AND row_count IS NULL AND column_names IS NULL "
            "AND uploaded_at IS NULL) OR (original_filename IS NOT NULL "
            "AND storage_key IS NOT NULL AND content_sha256 IS NOT NULL "
            "AND size_bytes IS NOT NULL AND row_count IS NOT NULL "
            "AND column_names IS NOT NULL AND uploaded_at IS NOT NULL))",
            name="ck_datasets_upload_metadata_all_or_none",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_datasets_updated_not_before_created",
        ),
        sa.CheckConstraint(
            "uploaded_at IS NULL OR (uploaded_at >= created_at AND updated_at >= uploaded_at)",
            name="ck_datasets_upload_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name="fk_datasets_owner_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.UniqueConstraint("storage_key", name="uq_datasets_storage_key"),
    )
    op.create_index(
        "ix_datasets_owner_created_id",
        "datasets",
        ["owner_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "validation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("rule_type", sa.String(length=16), nullable=False),
        sa.Column("target_column", sa.String(length=128), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rule_type IN ('required', 'unique', 'type', 'range', 'regex')",
            name="ck_validation_rules_type",
        ),
        sa.CheckConstraint(
            "char_length(target_column) BETWEEN 1 AND 128 AND target_column = btrim(target_column)",
            name="ck_validation_rules_target_column",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(configuration) = 'object'",
            name="ck_validation_rules_configuration_object",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_validation_rules_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_validation_rules"),
        sa.UniqueConstraint(
            "dataset_id",
            "rule_type",
            "target_column",
            "configuration",
            name="uq_validation_rules_definition",
        ),
    )
    op.create_index(
        "ix_validation_rules_dataset_created_id",
        "validation_rules",
        ["dataset_id", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_validation_rules_dataset_created_id", table_name="validation_rules")
    op.drop_table("validation_rules")
    op.drop_index("ix_datasets_owner_created_id", table_name="datasets")
    op.drop_table("datasets")
