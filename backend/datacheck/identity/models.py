import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from datacheck.infrastructure.database import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class User(Base):
    """Authentication identity persisted independently of HTTP concerns."""

    __tablename__ = "users"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_users"),
        UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        CheckConstraint(
            "octet_length(email) BETWEEN 3 AND 254",
            name="ck_users_email_octet_length",
        ),
        CheckConstraint(
            "octet_length(email_normalized) BETWEEN 3 AND 254",
            name="ck_users_email_normalized_octet_length",
        ),
        CheckConstraint(
            "email_normalized = lower(email_normalized)",
            name="ck_users_email_normalized_lowercase",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_users_updated_not_before_created",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now, nullable=False
    )


class UserSession(Base):
    """Server-side session state that never persists its bearer token."""

    __tablename__ = "sessions"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_sessions"),
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        CheckConstraint(
            "octet_length(token_hash) = 32",
            name="ck_sessions_token_hash_length",
        ),
        CheckConstraint(
            "octet_length(csrf_token) = 32",
            name="ck_sessions_csrf_token_length",
        ),
        CheckConstraint(
            "last_seen_at >= created_at",
            name="ck_sessions_last_seen_not_before_created",
        ),
        CheckConstraint(
            "last_seen_at <= absolute_expires_at",
            name="ck_sessions_last_seen_not_after_absolute_expiry",
        ),
        CheckConstraint(
            "absolute_expires_at = created_at + interval '12 hours'",
            name="ck_sessions_absolute_lifetime",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_sessions_revoked_not_before_created",
        ),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_last_seen_at", "last_seen_at"),
        Index("ix_sessions_absolute_expires_at", "absolute_expires_at"),
        Index(
            "ix_sessions_revoked_at",
            "revoked_at",
            postgresql_where=text("revoked_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", name="fk_sessions_user_id_users", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    csrf_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
