"""Create identity and sessions.

Revision ID: 0001_identity_sessions
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_identity_sessions"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("email_normalized", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(email) BETWEEN 3 AND 254",
            name="ck_users_email_octet_length",
        ),
        sa.CheckConstraint(
            "octet_length(email_normalized) BETWEEN 3 AND 254",
            name="ck_users_email_normalized_octet_length",
        ),
        sa.CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_users_email_normalized_lowercase",
        ),
        sa.CheckConstraint(
            "updated_at >= created_at",
            name="ck_users_updated_not_before_created",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_token", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_sessions_token_hash_length",
        ),
        sa.CheckConstraint(
            "octet_length(csrf_token) = 32",
            name="ck_sessions_csrf_token_length",
        ),
        sa.CheckConstraint(
            "last_seen_at >= created_at",
            name="ck_sessions_last_seen_not_before_created",
        ),
        sa.CheckConstraint(
            "last_seen_at <= absolute_expires_at",
            name="ck_sessions_last_seen_not_after_absolute_expiry",
        ),
        sa.CheckConstraint(
            "absolute_expires_at = created_at + interval '12 hours'",
            name="ck_sessions_absolute_lifetime",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_sessions_revoked_not_before_created",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_index("ix_sessions_last_seen_at", "sessions", ["last_seen_at"], unique=False)
    op.create_index(
        "ix_sessions_absolute_expires_at",
        "sessions",
        ["absolute_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_sessions_revoked_at",
        "sessions",
        ["revoked_at"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_revoked_at", table_name="sessions")
    op.drop_index("ix_sessions_absolute_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_last_seen_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
