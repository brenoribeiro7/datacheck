"""Create immutable analyses and validation results.

Revision ID: 0003_analysis_results_score
Revises: 0002_datasets_rules_csv
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_analysis_results_score"
down_revision: str | None = "0002_datasets_rules_csv"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("source_original_filename", sa.String(length=255), nullable=False),
        sa.Column("source_content_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("source_row_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "source_column_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_violation_count", sa.BigInteger(), nullable=False),
        sa.Column("quality_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(source_content_sha256) = 32",
            name="ck_analyses_source_content_sha256_length",
        ),
        sa.CheckConstraint(
            "source_size_bytes BETWEEN 1 AND 10485760",
            name="ck_analyses_source_size_bytes",
        ),
        sa.CheckConstraint("source_row_count >= 0", name="ck_analyses_source_row_count"),
        sa.CheckConstraint(
            "jsonb_typeof(source_column_names) = 'array' "
            "AND jsonb_array_length(source_column_names) BETWEEN 1 AND 256",
            name="ck_analyses_source_column_names",
        ),
        sa.CheckConstraint(
            "total_violation_count >= 0",
            name="ck_analyses_total_violation_count",
        ),
        sa.CheckConstraint(
            "quality_score IS NULL OR quality_score BETWEEN 0.00 AND 100.00",
            name="ck_analyses_quality_score",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name="fk_analyses_dataset_id_datasets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analyses"),
    )
    op.create_index(
        "ix_analyses_dataset_created_id",
        "analyses",
        ["dataset_id", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "validation_results",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("rule_position", sa.Integer(), nullable=False),
        sa.Column("source_rule_id", sa.Uuid(), nullable=False),
        sa.Column("rule_type", sa.String(length=16), nullable=False),
        sa.Column("target_column", sa.String(length=128), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evaluated_count", sa.BigInteger(), nullable=False),
        sa.Column("passed_count", sa.BigInteger(), nullable=False),
        sa.Column("violation_count", sa.BigInteger(), nullable=False),
        sa.Column("skipped_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "violation_samples",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rule_position >= 0",
            name="ck_validation_results_rule_position",
        ),
        sa.CheckConstraint(
            "rule_type IN ('required', 'unique', 'type', 'range', 'regex')",
            name="ck_validation_results_rule_type",
        ),
        sa.CheckConstraint(
            "char_length(target_column) BETWEEN 1 AND 128 AND target_column = btrim(target_column)",
            name="ck_validation_results_target_column",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(configuration) = 'object'",
            name="ck_validation_results_configuration_object",
        ),
        sa.CheckConstraint(
            "evaluated_count >= 0 AND passed_count >= 0 "
            "AND violation_count >= 0 AND skipped_count >= 0",
            name="ck_validation_results_nonnegative_counts",
        ),
        sa.CheckConstraint(
            "evaluated_count = passed_count + violation_count",
            name="ck_validation_results_count_balance",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(violation_samples) = 'array' "
            "AND jsonb_array_length(violation_samples) <= 20",
            name="ck_validation_results_violation_samples",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name="fk_validation_results_analysis_id_analyses",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "analysis_id",
            "rule_position",
            name="pk_validation_results",
        ),
        sa.UniqueConstraint(
            "analysis_id",
            "source_rule_id",
            name="uq_validation_results_analysis_source_rule",
        ),
    )


def downgrade() -> None:
    op.drop_table("validation_results")
    op.drop_index("ix_analyses_dataset_created_id", table_name="analyses")
    op.drop_table("analyses")
