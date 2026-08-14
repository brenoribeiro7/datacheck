import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from datacheck.identity.models import User, UserSession


@dataclass(frozen=True, slots=True)
class UserCredentialSnapshot:
    user_id: uuid.UUID
    password_hash: str


@dataclass(frozen=True, slots=True)
class UserPublicSnapshot:
    user_id: uuid.UUID
    email: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ActiveSessionSnapshot:
    session_id: uuid.UUID
    user_id: uuid.UUID
    csrf_token: bytes
    absolute_expires_at: datetime


class UserRepository:
    """Perform identity persistence operations without owning transactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> None:
        self._session.add(user)

    def get_credentials_by_email(self, email_normalized: str) -> UserCredentialSnapshot | None:
        statement = select(User.id, User.password_hash).where(
            User.email_normalized == email_normalized
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return UserCredentialSnapshot(user_id=row.id, password_hash=row.password_hash)

    def get_for_update(self, user_id: uuid.UUID) -> User | None:
        statement = select(User).where(User.id == user_id).with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def get_public(self, user_id: uuid.UUID) -> UserPublicSnapshot | None:
        statement = select(User.id, User.email, User.created_at).where(User.id == user_id)
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return UserPublicSnapshot(user_id=row.id, email=row.email, created_at=row.created_at)


class SessionRepository:
    """Persist and atomically transition server-side session state."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user_session: UserSession) -> None:
        self._session.add(user_session)

    def authenticate_and_touch(
        self,
        *,
        token_hash: bytes,
        now: datetime,
        idle_timeout: timedelta,
    ) -> ActiveSessionSnapshot | None:
        # The predicates and monotonic touch execute as one row-locking statement,
        # so concurrent requests cannot re-activate or regress a session.
        statement = (
            update(UserSession)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.absolute_expires_at > now,
                UserSession.last_seen_at > now - idle_timeout,
            )
            .values(last_seen_at=func.greatest(UserSession.last_seen_at, now))
            .returning(
                UserSession.id,
                UserSession.user_id,
                UserSession.csrf_token,
                UserSession.absolute_expires_at,
            )
            .execution_options(synchronize_session=False)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return ActiveSessionSnapshot(
            session_id=row.id,
            user_id=row.user_id,
            csrf_token=row.csrf_token,
            absolute_expires_at=row.absolute_expires_at,
        )

    def get_for_update_by_token_hash(self, token_hash: bytes) -> UserSession | None:
        statement = (
            select(UserSession).where(UserSession.token_hash == token_hash).with_for_update()
        )
        return self._session.execute(statement).scalar_one_or_none()

    def delete_inactive_batch(
        self,
        *,
        now: datetime,
        idle_timeout: timedelta,
        limit: int,
    ) -> int:
        inactive = or_(
            UserSession.revoked_at.is_not(None),
            UserSession.absolute_expires_at <= now,
            UserSession.last_seen_at <= now - idle_timeout,
        )
        ids_statement = (
            select(UserSession.id)
            .where(inactive)
            .order_by(UserSession.absolute_expires_at, UserSession.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        session_ids = list(self._session.scalars(ids_statement))
        if not session_ids:
            return 0
        statement = (
            delete(UserSession)
            .where(UserSession.id.in_(session_ids))
            .execution_options(synchronize_session=False)
        )
        self._session.execute(statement)
        return len(session_ids)
