from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Literal, Self, cast

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from datacheck.identity.models import User, UserSession
from datacheck.identity.passwords import PasswordPolicyError, PasswordService, PasswordVerification
from datacheck.identity.repositories import (
    ActiveSessionSnapshot,
    SessionRepository,
    UserCredentialSnapshot,
    UserPublicSnapshot,
    UserRepository,
)
from datacheck.identity.service import (
    ABSOLUTE_TIMEOUT,
    CLEANUP_BATCH_SIZE,
    IDLE_TIMEOUT,
    AuthenticationRequired,
    DuplicateIdentity,
    IdentityService,
    InvalidCredentials,
    InvalidCsrf,
    LogoutResult,
    SessionState,
)
from datacheck.identity.tokens import decode_token, encode_token, hash_session_token

_NOW = datetime(2026, 2, 1, 12, tzinfo=UTC)
_PASSWORD = "valid-password-1"


class _FakeTransaction(AbstractContextManager[None]):
    def __init__(self, database_session: _FakeSession) -> None:
        self._database_session = database_session

    def __enter__(self) -> None:
        self._database_session.transaction_active = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        self._database_session.transaction_active = False
        self._database_session.rolled_back = exc_type is not None
        return False


class _FakeSession:
    def __init__(self) -> None:
        self.transaction_active = False
        self.rolled_back = False
        self.flush_error: BaseException | None = None
        self.flush_count = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        return False

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    def flush(self) -> None:
        self.flush_count += 1
        if self.flush_error is not None:
            raise self.flush_error


class _FakeFactory:
    def __init__(self, session_configurator: Callable[[_FakeSession], None] | None = None) -> None:
        self.sessions: list[_FakeSession] = []
        self._session_configurator = session_configurator

    def __call__(self) -> _FakeSession:
        database_session = _FakeSession()
        if self._session_configurator is not None:
            self._session_configurator(database_session)
        self.sessions.append(database_session)
        return database_session

    @property
    def transaction_active(self) -> bool:
        return any(item.transaction_active for item in self.sessions)

    def as_session_factory(self) -> sessionmaker[Session]:
        return cast(sessionmaker[Session], self)


class _PasswordProbe(PasswordService):
    def __init__(self, factory: _FakeFactory) -> None:
        self.factory = factory
        self.hash_inputs: list[str] = []
        self.verify_inputs: list[tuple[str, str]] = []
        self.verifications: dict[str, PasswordVerification] = {}
        self.needs_rehash = False

    def normalize_and_validate(self, password: str) -> str:
        if not 15 <= len(password) <= 128:
            raise PasswordPolicyError("password length is outside the accepted range")
        return password

    def hash(self, password: str) -> str:
        assert self.factory.transaction_active is False
        self.hash_inputs.append(password)
        return f"probe-hash-{len(self.hash_inputs)}"

    def verify(self, encoded_hash: str, password: str) -> PasswordVerification:
        assert self.factory.transaction_active is False
        self.verify_inputs.append((encoded_hash, password))
        return self.verifications.get(encoded_hash, PasswordVerification.MATCH)

    def check_needs_rehash(self, encoded_hash: str) -> bool:
        return self.needs_rehash


def _service(
    factory: _FakeFactory,
    password_service: _PasswordProbe | None = None,
    *,
    clock: Callable[[], datetime] = lambda: _NOW,
) -> tuple[IdentityService, _PasswordProbe]:
    password_probe = password_service or _PasswordProbe(factory)
    return (
        IdentityService(
            session_factory=factory.as_session_factory(),
            password_service=password_probe,
            clock=clock,
        ),
        password_probe,
    )


def _patch_registration_repositories(
    monkeypatch: pytest.MonkeyPatch,
    *,
    users: list[User],
    sessions: list[UserSession],
    cleanup: Callable[..., int] | None = None,
) -> None:
    monkeypatch.setattr(UserRepository, "add", lambda _self, user: users.append(user))
    monkeypatch.setattr(
        SessionRepository,
        "add",
        lambda _self, user_session: sessions.append(user_session),
    )
    monkeypatch.setattr(
        SessionRepository,
        "delete_inactive_batch",
        cleanup or (lambda _self, **_kwargs: 0),
    )


def test_registration_prepares_credentials_before_transaction_and_commits_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    users: list[User] = []
    sessions: list[UserSession] = []
    cleanup_calls: list[dict[str, Any]] = []

    def record_cleanup(_repository: SessionRepository, **kwargs: Any) -> int:
        cleanup_calls.append(kwargs)
        return 0

    _patch_registration_repositories(
        monkeypatch,
        users=users,
        sessions=sessions,
        cleanup=record_cleanup,
    )
    service, passwords = _service(factory)

    result = service.register(email="  Person@EXAMPLE.TEST  ", password=_PASSWORD)

    assert len(passwords.hash_inputs) == 2  # one process-lifetime dummy plus registration
    assert users[0].email == "Person@example.test"
    assert users[0].email_normalized == "person@example.test"
    assert result.user.user_id == users[0].id
    assert result.user.email == users[0].email
    assert result.user.created_at == _NOW
    assert result.user.updated_at == _NOW
    assert result.user.created_at == result.user.updated_at
    assert {item.name for item in fields(result.user)} == {
        "user_id",
        "email",
        "created_at",
        "updated_at",
    }
    assert sessions[0].user_id == users[0].id
    assert sessions[0].token_hash == hash_session_token(decode_token(result.bearer_token))
    assert sessions[0].csrf_token == decode_token(result.csrf_token)
    assert sessions[0].absolute_expires_at == _NOW + ABSOLUTE_TIMEOUT
    assert cleanup_calls == [{"now": _NOW, "idle_timeout": IDLE_TIMEOUT, "limit": 100}]
    assert len(factory.sessions) == 2
    assert result.bearer_token not in repr(result)
    assert result.csrf_token not in repr(result)


class _Diagnostic:
    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


class _DatabaseOrigin(Exception):
    def __init__(self, constraint_name: str) -> None:
        self.diag = _Diagnostic(constraint_name)


@pytest.mark.parametrize(
    ("constraint", "expected_exception"),
    [
        ("uq_users_email_normalized", DuplicateIdentity),
        ("ck_sessions_csrf_token_length", IntegrityError),
    ],
)
def test_registration_maps_only_duplicate_identity_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    constraint: str,
    expected_exception: type[BaseException],
) -> None:
    error = IntegrityError("insert", {}, _DatabaseOrigin(constraint))
    factory = _FakeFactory(lambda item: setattr(item, "flush_error", error))
    _patch_registration_repositories(monkeypatch, users=[], sessions=[])
    service, _ = _service(factory)

    with pytest.raises(expected_exception):
        service.register(email="person@example.test", password=_PASSWORD)

    assert factory.sessions[0].rolled_back is True
    assert len(factory.sessions) == 1


def test_cleanup_database_failure_does_not_invalidate_committed_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    _patch_registration_repositories(
        monkeypatch,
        users=[],
        sessions=[],
        cleanup=lambda _self, **_kwargs: (_ for _ in ()).throw(SQLAlchemyError("synthetic")),
    )
    service, _ = _service(factory)

    result = service.register(email="person@example.test", password=_PASSWORD)

    assert result.user.email == "person@example.test"
    assert factory.sessions[0].rolled_back is False
    assert factory.sessions[1].rolled_back is True


@pytest.mark.parametrize("email", ["unknown@example.test", "invalid-address"])
def test_unknown_or_invalid_email_runs_dummy_verification_without_open_transaction(
    monkeypatch: pytest.MonkeyPatch,
    email: str,
) -> None:
    factory = _FakeFactory()
    monkeypatch.setattr(UserRepository, "get_credentials_by_email", lambda _self, _email: None)
    service, passwords = _service(factory)
    dummy_hash = passwords.hash_inputs and "probe-hash-1"

    with pytest.raises(InvalidCredentials):
        service.login(email=email, password=_PASSWORD)

    assert passwords.verify_inputs == [(dummy_hash, _PASSWORD)]
    assert factory.transaction_active is False


def test_malformed_stored_hash_runs_dummy_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    snapshot = UserCredentialSnapshot(user_id=uuid.uuid4(), password_hash="malformed")
    monkeypatch.setattr(
        UserRepository,
        "get_credentials_by_email",
        lambda _self, _email: snapshot,
    )
    service, passwords = _service(factory)
    passwords.verifications["malformed"] = PasswordVerification.MALFORMED

    with pytest.raises(InvalidCredentials):
        service.login(email="person@example.test", password=_PASSWORD)

    assert passwords.verify_inputs == [
        ("malformed", _PASSWORD),
        ("probe-hash-1", _PASSWORD),
    ]


def test_login_rehashes_outside_transaction_and_issues_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    user = User(
        id=uuid.uuid4(),
        email="person@example.test",
        email_normalized="person@example.test",
        password_hash="verified-hash",
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(days=1),
    )
    snapshot = UserCredentialSnapshot(user_id=user.id, password_hash=user.password_hash)
    added_sessions: list[UserSession] = []
    monkeypatch.setattr(
        UserRepository,
        "get_credentials_by_email",
        lambda _self, _email: snapshot,
    )
    monkeypatch.setattr(UserRepository, "get_for_update", lambda _self, _id: user)
    monkeypatch.setattr(
        SessionRepository,
        "add",
        lambda _self, user_session: added_sessions.append(user_session),
    )
    monkeypatch.setattr(SessionRepository, "delete_inactive_batch", lambda _self, **_kwargs: 0)
    service, passwords = _service(factory)
    passwords.needs_rehash = True

    result = service.login(email=user.email, password=_PASSWORD)

    assert passwords.verify_inputs == [("verified-hash", _PASSWORD)]
    assert user.password_hash == "probe-hash-2"
    assert user.updated_at == _NOW
    assert result.user.updated_at == _NOW
    assert added_sessions[0].id == result.session_id
    assert added_sessions[0].token_hash == hash_session_token(decode_token(result.bearer_token))
    assert factory.transaction_active is False


def test_login_without_rehash_preserves_public_updated_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    stored_updated_at = _NOW - timedelta(days=1)
    user = User(
        id=uuid.uuid4(),
        email="person@example.test",
        email_normalized="person@example.test",
        password_hash="verified-hash",
        created_at=stored_updated_at,
        updated_at=stored_updated_at,
    )
    snapshot = UserCredentialSnapshot(user_id=user.id, password_hash=user.password_hash)
    monkeypatch.setattr(
        UserRepository,
        "get_credentials_by_email",
        lambda _self, _email: snapshot,
    )
    monkeypatch.setattr(UserRepository, "get_for_update", lambda _self, _id: user)
    monkeypatch.setattr(SessionRepository, "add", lambda _self, _session: None)
    monkeypatch.setattr(SessionRepository, "delete_inactive_batch", lambda _self, **_kwargs: 0)
    service, _ = _service(factory)

    result = service.login(email=user.email, password=_PASSWORD)

    assert result.user.updated_at == stored_updated_at
    assert user.updated_at == stored_updated_at


def test_stale_verified_hash_does_not_create_session(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _FakeFactory()
    user_id = uuid.uuid4()
    snapshot = UserCredentialSnapshot(user_id=user_id, password_hash="verified-hash")
    stale_user = User(
        id=user_id,
        email="person@example.test",
        email_normalized="person@example.test",
        password_hash="changed-hash",
        created_at=_NOW,
        updated_at=_NOW,
    )
    added_sessions: list[UserSession] = []
    monkeypatch.setattr(
        UserRepository,
        "get_credentials_by_email",
        lambda _self, _email: snapshot,
    )
    monkeypatch.setattr(UserRepository, "get_for_update", lambda _self, _id: stale_user)
    monkeypatch.setattr(
        SessionRepository,
        "add",
        lambda _self, item: added_sessions.append(item),
    )
    service, _ = _service(factory)

    with pytest.raises(InvalidCredentials):
        service.login(email=stale_user.email, password=_PASSWORD)

    assert added_sessions == []
    assert factory.sessions[1].rolled_back is True


def test_authenticate_returns_public_context_and_converges_malformed_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    service, _ = _service(factory)
    raw_bearer = bytes(range(32))
    user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    monkeypatch.setattr(
        SessionRepository,
        "authenticate_and_touch",
        lambda _self, **_kwargs: ActiveSessionSnapshot(
            session_id=session_id,
            user_id=user_id,
            csrf_token=b"c" * 32,
            absolute_expires_at=_NOW + timedelta(hours=1),
        ),
    )
    monkeypatch.setattr(
        UserRepository,
        "get_public",
        lambda _self, _id: UserPublicSnapshot(
            user_id=user_id,
            email="person@example.test",
            created_at=_NOW - timedelta(days=1),
            updated_at=_NOW - timedelta(hours=1),
        ),
    )

    context = service.authenticate(encode_token(raw_bearer))

    assert context.session_id == session_id
    assert context.user.email == "person@example.test"
    assert context.user.updated_at == _NOW - timedelta(hours=1)
    assert "password" not in repr(context)
    assert "token_hash" not in repr(context)
    assert "bearer" not in repr(context)
    with pytest.raises(AuthenticationRequired):
        service.authenticate("malformed")
    with pytest.raises(AuthenticationRequired):
        service.authenticate(None)


def test_logout_requires_valid_csrf_only_for_active_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    service, _ = _service(factory)
    raw_bearer = bytes(range(32))
    user_session = UserSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash=hash_session_token(raw_bearer),
        csrf_token=b"c" * 32,
        created_at=_NOW - timedelta(hours=1),
        last_seen_at=_NOW - timedelta(minutes=1),
        absolute_expires_at=_NOW + timedelta(hours=11),
        revoked_at=None,
    )
    monkeypatch.setattr(
        SessionRepository,
        "get_for_update_by_token_hash",
        lambda _self, _hash: user_session,
    )

    with pytest.raises(InvalidCsrf):
        service.logout(encoded_bearer=encode_token(raw_bearer), supplied_csrf_token=b"x" * 32)
    assert user_session.revoked_at is None

    assert (
        service.logout(encoded_bearer=encode_token(raw_bearer), supplied_csrf_token=b"c" * 32)
        is LogoutResult.REVOKED
    )
    assert user_session.revoked_at == _NOW
    assert (
        service.logout(encoded_bearer=encode_token(raw_bearer), supplied_csrf_token=None)
        is LogoutResult.ALREADY_INACTIVE
    )


def test_session_state_precedence_and_inclusive_boundaries() -> None:
    user_session = UserSession(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        token_hash=b"t" * 32,
        csrf_token=b"c" * 32,
        created_at=_NOW - timedelta(hours=12),
        last_seen_at=_NOW - IDLE_TIMEOUT,
        absolute_expires_at=_NOW,
        revoked_at=_NOW - timedelta(hours=1),
    )

    assert IdentityService._classify_session(user_session, _NOW) is SessionState.REVOKED
    user_session.revoked_at = None
    assert IdentityService._classify_session(user_session, _NOW) is SessionState.ABSOLUTE_EXPIRED
    user_session.absolute_expires_at = _NOW + timedelta(seconds=1)
    assert IdentityService._classify_session(user_session, _NOW) is SessionState.IDLE_EXPIRED
    user_session.last_seen_at = _NOW - IDLE_TIMEOUT + timedelta(microseconds=1)
    assert IdentityService._classify_session(user_session, _NOW) is SessionState.ACTIVE


def test_cleanup_passes_bounded_batch_and_naive_clock_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _FakeFactory()
    cleanup_calls: list[dict[str, Any]] = []

    def record_cleanup(_repository: SessionRepository, **kwargs: Any) -> int:
        cleanup_calls.append(kwargs)
        return 7

    monkeypatch.setattr(
        SessionRepository,
        "delete_inactive_batch",
        record_cleanup,
    )
    service, _ = _service(factory)

    assert service.cleanup_inactive_sessions() == 7
    assert cleanup_calls == [
        {"now": _NOW, "idle_timeout": IDLE_TIMEOUT, "limit": CLEANUP_BATCH_SIZE}
    ]

    naive_service, _ = _service(factory, clock=lambda: datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="timezone-aware"):
        naive_service.cleanup_inactive_sessions()
