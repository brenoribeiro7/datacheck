import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from datacheck.identity.email import EmailPolicyError, canonicalize_email
from datacheck.identity.models import User, UserSession
from datacheck.identity.passwords import PasswordService, PasswordVerification
from datacheck.identity.repositories import SessionRepository, UserRepository
from datacheck.identity.tokens import (
    TokenEncodingError,
    csrf_tokens_match,
    decode_token,
    encode_token,
    generate_token_bytes,
    hash_session_token,
)

IDLE_TIMEOUT = timedelta(hours=2)
ABSOLUTE_TIMEOUT = timedelta(hours=12)
CLEANUP_BATCH_SIZE = 100


class DuplicateIdentity(Exception):
    """Indicate that the normalized identity already exists."""


class InvalidCredentials(Exception):
    """Represent a generic credential failure without disclosing its cause."""


class AuthenticationRequired(Exception):
    """Converge missing, malformed, unknown, revoked, and expired sessions."""


class InvalidCsrf(Exception):
    """Indicate a failed synchronizer-token check for an active session."""


class SessionState(Enum):
    REVOKED = "revoked"
    ABSOLUTE_EXPIRED = "absolute_expired"
    IDLE_EXPIRED = "idle_expired"
    ACTIVE = "active"


class LogoutResult(Enum):
    REVOKED = "revoked"
    ALREADY_INACTIVE = "already_inactive"


@dataclass(frozen=True, slots=True)
class UserReference:
    user_id: uuid.UUID
    email: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SessionIssuance:
    user: UserReference
    session_id: uuid.UUID
    bearer_token: str = field(repr=False)
    csrf_token: str = field(repr=False)
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedContext:
    user: UserReference
    session_id: uuid.UUID
    csrf_token: bytes = field(repr=False)
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True)
class _SessionMaterial:
    row: UserSession
    bearer_token: str = field(repr=False)
    csrf_token: str = field(repr=False)


class IdentityService:
    """Coordinate identity use cases while owning every transaction boundary."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        password_service: PasswordService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._password_service = password_service
        self._clock = clock or (lambda: datetime.now(UTC))
        dummy_password = encode_token(generate_token_bytes())
        self._dummy_password_hash = self._password_service.hash(dummy_password)

    def register(self, *, email: str, password: str) -> SessionIssuance:
        canonical_email = canonicalize_email(email)
        normalized_password = self._password_service.normalize_and_validate(password)
        password_hash = self._password_service.hash(normalized_password)
        now = self._now()
        user = User(
            id=uuid.uuid4(),
            email=canonical_email.email,
            email_normalized=canonical_email.email_normalized,
            password_hash=password_hash,
            created_at=now,
            updated_at=now,
        )
        material = self._issue_session(user_id=user.id, now=now)

        try:
            with self._session_factory() as database_session, database_session.begin():
                UserRepository(database_session).add(user)
                SessionRepository(database_session).add(material.row)
                database_session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_users_email_normalized":
                raise DuplicateIdentity("identity already exists") from None
            raise

        result = SessionIssuance(
            user=UserReference(
                user_id=user.id,
                email=user.email,
                created_at=user.created_at,
                updated_at=user.updated_at,
            ),
            session_id=material.row.id,
            bearer_token=material.bearer_token,
            csrf_token=material.csrf_token,
            absolute_expires_at=material.row.absolute_expires_at,
        )
        self._cleanup_after_success(now)
        return result

    def login(self, *, email: str, password: str) -> SessionIssuance:
        normalized_password = self._password_service.normalize_and_validate(password)
        try:
            canonical_email = canonicalize_email(email)
        except (EmailPolicyError, TypeError):
            self._verify_dummy(normalized_password)
            raise InvalidCredentials("invalid credentials") from None

        with self._session_factory() as database_session, database_session.begin():
            snapshot = UserRepository(database_session).get_credentials_by_email(
                canonical_email.email_normalized
            )

        if snapshot is None:
            self._verify_dummy(normalized_password)
            raise InvalidCredentials("invalid credentials")

        verification = self._password_service.verify(snapshot.password_hash, normalized_password)
        if verification is PasswordVerification.MISMATCH:
            raise InvalidCredentials("invalid credentials")
        if verification is PasswordVerification.MALFORMED:
            self._verify_dummy(normalized_password)
            raise InvalidCredentials("invalid credentials")

        replacement_hash: str | None = None
        if self._password_service.check_needs_rehash(snapshot.password_hash):
            replacement_hash = self._password_service.hash(normalized_password)

        now = self._now()
        material = self._issue_session(user_id=snapshot.user_id, now=now)
        with self._session_factory() as database_session, database_session.begin():
            user = UserRepository(database_session).get_for_update(snapshot.user_id)
            if user is None or user.password_hash != snapshot.password_hash:
                raise InvalidCredentials("invalid credentials")
            if replacement_hash is not None:
                user.password_hash = replacement_hash
                user.updated_at = now
            SessionRepository(database_session).add(material.row)
            database_session.flush()
            user_reference = UserReference(
                user_id=user.id,
                email=user.email,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )

        result = SessionIssuance(
            user=user_reference,
            session_id=material.row.id,
            bearer_token=material.bearer_token,
            csrf_token=material.csrf_token,
            absolute_expires_at=material.row.absolute_expires_at,
        )
        self._cleanup_after_success(now)
        return result

    def authenticate(self, encoded_bearer: str | None) -> AuthenticatedContext:
        try:
            if encoded_bearer is None:
                raise TokenEncodingError("missing token")
            token_hash = hash_session_token(decode_token(encoded_bearer))
        except (TokenEncodingError, TypeError):
            raise AuthenticationRequired("authentication required") from None
        now = self._now()

        with self._session_factory() as database_session, database_session.begin():
            active_session = SessionRepository(database_session).authenticate_and_touch(
                token_hash=token_hash,
                now=now,
                idle_timeout=IDLE_TIMEOUT,
            )
            if active_session is None:
                raise AuthenticationRequired("authentication required")
            user = UserRepository(database_session).get_public(active_session.user_id)
            if user is None:
                raise AuthenticationRequired("authentication required")
            return AuthenticatedContext(
                user=UserReference(
                    user_id=user.user_id,
                    email=user.email,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                ),
                session_id=active_session.session_id,
                csrf_token=active_session.csrf_token,
                absolute_expires_at=active_session.absolute_expires_at,
            )

    def logout(
        self,
        *,
        encoded_bearer: str | None,
        supplied_csrf_token: bytes | None,
    ) -> LogoutResult:
        try:
            if encoded_bearer is None:
                raise TokenEncodingError("missing token")
            token_hash = hash_session_token(decode_token(encoded_bearer))
        except (TokenEncodingError, TypeError):
            return LogoutResult.ALREADY_INACTIVE
        now = self._now()

        with self._session_factory() as database_session, database_session.begin():
            user_session = SessionRepository(database_session).get_for_update_by_token_hash(
                token_hash
            )
            if (
                user_session is None
                or self._classify_session(user_session, now) is not SessionState.ACTIVE
            ):
                return LogoutResult.ALREADY_INACTIVE
            if supplied_csrf_token is None or not csrf_tokens_match(
                user_session.csrf_token, supplied_csrf_token
            ):
                raise InvalidCsrf("invalid CSRF token")
            user_session.revoked_at = now
            database_session.flush()
            return LogoutResult.REVOKED

    def cleanup_inactive_sessions(self, *, now: datetime | None = None) -> int:
        cleanup_now = self._validate_time(now) if now is not None else self._now()
        with self._session_factory() as database_session, database_session.begin():
            return SessionRepository(database_session).delete_inactive_batch(
                now=cleanup_now,
                idle_timeout=IDLE_TIMEOUT,
                limit=CLEANUP_BATCH_SIZE,
            )

    def _cleanup_after_success(self, now: datetime) -> None:
        try:
            self.cleanup_inactive_sessions(now=now)
        except SQLAlchemyError:
            # Authentication is already committed. Cleanup is deliberately best-effort
            # and must not retroactively invalidate the newly issued session.
            return

    def _issue_session(self, *, user_id: uuid.UUID, now: datetime) -> _SessionMaterial:
        raw_bearer = generate_token_bytes()
        raw_csrf = generate_token_bytes()
        user_session = UserSession(
            id=uuid.uuid4(),
            user_id=user_id,
            token_hash=hash_session_token(raw_bearer),
            csrf_token=raw_csrf,
            created_at=now,
            last_seen_at=now,
            absolute_expires_at=now + ABSOLUTE_TIMEOUT,
            revoked_at=None,
        )
        return _SessionMaterial(
            row=user_session,
            bearer_token=encode_token(raw_bearer),
            csrf_token=encode_token(raw_csrf),
        )

    def _verify_dummy(self, normalized_password: str) -> None:
        self._password_service.verify(self._dummy_password_hash, normalized_password)

    def _now(self) -> datetime:
        return self._validate_time(self._clock())

    @staticmethod
    def _validate_time(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("identity clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _classify_session(user_session: UserSession, now: datetime) -> SessionState:
        if user_session.revoked_at is not None:
            return SessionState.REVOKED
        if user_session.absolute_expires_at <= now:
            return SessionState.ABSOLUTE_EXPIRED
        if user_session.last_seen_at <= now - IDLE_TIMEOUT:
            return SessionState.IDLE_EXPIRED
        return SessionState.ACTIVE

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        diagnostic = getattr(error.orig, "diag", None)
        name = getattr(diagnostic, "constraint_name", None)
        return name if isinstance(name, str) else None
